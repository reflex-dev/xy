// ---------------------------------------------------------------------------
// ChartView
// ---------------------------------------------------------------------------

const MARGIN = { l: 62, r: 14, t: 10, b: 42 };
const UNITLESS_STYLE_PROPS = new Set([
  "animation-iteration-count",
  "aspect-ratio",
  "border-image-outset",
  "border-image-slice",
  "border-image-width",
  "column-count",
  "flex",
  "flex-grow",
  "flex-shrink",
  "font-weight",
  "line-height",
  "opacity",
  "order",
  "orphans",
  "tab-size",
  "widows",
  "z-index",
  "zoom",
  "fill-opacity",
  "flood-opacity",
  "stop-opacity",
  "stroke-miterlimit",
  "stroke-opacity",
]);

class ChartView {
  constructor(el, spec, buffer, comm) {
    if (spec.protocol !== PROTOCOL) {
      el.textContent =
        `fastcharts: protocol mismatch (client speaks ${PROTOCOL}, kernel sent ${spec.protocol}). ` +
        "Update the fastcharts package and restart the kernel.";
      throw new Error("protocol mismatch");
    }
    this.spec = spec;
    this.interaction = spec.interaction || {};
    this.markStyle = spec.mark_style || {};
    this.axes = this._normalizeAxes(spec);
    this.comm = comm;
    this.seq = 0;
    this._densityStamp = 0;
    this._viewRequestBurstStart = null;
    this._viewAnim = null;
    this._animRaf = null;
    this._wheelZoomRaf = null;
    this._pendingWheelZoom = null;
    this._lastLabelDraw = null;
    this._lutCache = new Map();
    this._listeners = [];
    this._glPrograms = [];
    this._destroyed = false;
    this._hoverId = -1;
    this._hoverTarget = null;
    this._viewEventRaf = null;
    this._linkedSource = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    this.dragMode = "pan"; // "pan" | "zoom" (box zoom); toggled via the modebar

    // Responsive size: "100%" means the *container* owns that axis — measure
    // it now, track it with a ResizeObserver below. Numeric sizes are fixed.
    // (height:"100%" needs a parent with a defined height, per usual CSS.)
    this.fluid = spec.width === "100%";
    this.fluidH = spec.height === "100%";
    const rect = this.fluid || this.fluidH ? el.getBoundingClientRect() : null;
    const cw = this.fluid ? Math.round(rect.width) || 640 : spec.width; // 0 = hidden; RO corrects
    const ch = this.fluidH ? Math.round(rect.height) || 420 : spec.height;
    this.size = { w: Math.max(120, cw), h: Math.max(120, ch) };
    this._layout();

    this._buildDom(el);
    this.theme = readTheme(this.root);
    // Retained for GL context restore: the payload is screen-bounded (§29) so
    // keeping it is cheap, and every GPU object is rebuildable from
    // spec + payload by design (§18/§27).
    this._payload = buffer;
    this._glLost = false;
    this._initGl(buffer);
    this._initContextLossRecovery();
    this._initInteraction();
    this._buildModebar(this.root); // after theme (icon color) + canvas (cursor)

    if ((this.fluid || this.fluidH) && typeof ResizeObserver !== "undefined") {
      this._ro = new ResizeObserver((entries) => {
        const r = entries[entries.length - 1].contentRect;
        if (r.width || r.height) this._resize(r.width, r.height);
      });
      this._ro.observe(this.root);
    }
    this._armVisibilityResizeWatch();
    this._armDprWatch();

    this.view0 = {
      x0: spec.x_axis.range[0], x1: spec.x_axis.range[1],
      y0: spec.y_axis.range[0], y1: spec.y_axis.range[1],
    };
    this.view = { ...this.view0 };
    this._initLinkedCharts();

    this._themeWatch = window.matchMedia("(prefers-color-scheme: dark)");
    this._onScheme = () => this.refreshTheme();
    this._themeWatch.addEventListener?.("change", this._onScheme);

    this._unsubscribeComm = comm ? comm.onMessage((msg, buffers) => this._onKernelMsg(msg, buffers)) : null;
    this.draw();
  }

  _layout() {
    // Plot rect from the current size — margins fixed, data area flexes.
    const compact = this.size.w < 520;
    const marginLeft = compact ? 46 : MARGIN.l;
    const marginRight = compact ? 8 : MARGIN.r;
    const marginTop = compact ? 6 : MARGIN.t;
    const marginBottom = compact ? 36 : MARGIN.b;
    const topAxisRoom = this._axis("x").side === "top" ? (compact ? 26 : 32) : 0;
    const top = marginTop + (this.spec.title ? (compact ? 26 : 30) : 0) + topAxisRoom;
    const extraRightAxes = Object.values(this.axes || {}).filter((axis) =>
      axis && axis.id !== "y" && String(axis.id || "").startsWith("y") && axis.side === "right");
    const right = marginRight + (extraRightAxes.length ? (compact ? 42 : 54) : 0);
    this.plot = {
      x: marginLeft,
      y: top,
      w: Math.max(40, this.size.w - marginLeft - right),
      h: Math.max(40, this.size.h - top - marginBottom),
    };
  }

  _normalizeAxes(spec) {
    const axes = { ...(spec.axes || {}) };
    if (spec.x_axis) axes.x = spec.x_axis;
    if (spec.y_axis) axes.y = spec.y_axis;
    for (const [id, axis] of Object.entries(axes)) {
      if (axis && typeof axis === "object" && !axis.id) axis.id = id;
    }
    return axes;
  }

  _axis(axisId) {
    const id = axisId || "x";
    return this.axes[id] || (String(id).startsWith("y") ? this.axes.y : this.axes.x) || {};
  }

  _axisDim(axisId) {
    return String(axisId || "x").startsWith("y") ? "y" : "x";
  }

  _axisMode(axisId) {
    return this._axis(axisId).scale === "log" ? 1 : 0;
  }

  _axisCoord(axis, value) {
    const v = Number(value);
    if (!Number.isFinite(v)) return NaN;
    if (axis && axis.scale === "log") return v > 0 ? Math.log10(v) : NaN;
    return v;
  }

  _axisValue(axis, coord) {
    if (axis && axis.scale === "log") return Math.pow(10, coord);
    return coord;
  }

  _axisRange(axisId, view = this.view) {
    if (axisId === "x") return [view.x0, view.x1];
    if (axisId === "y") return [view.y0, view.y1];
    const axis = this._axis(axisId);
    const r = axis.range || [0, 1];
    return [Number(r[0]), Number(r[1])];
  }

  _axisTicks(axisId, target) {
    const axis = this._axis(axisId);
    const [lo, hi] = this._axisRange(axisId);
    if (axis.kind === "time") return timeTicks(lo, hi, target);
    if (axis.kind === "category") return categoryTicks(lo, hi, axis.categories || [], target);
    if (axis.scale === "log") return logTicks(lo, hi, target);
    return linearTicks(lo, hi, target);
  }

  _dataPx(axisId, value) {
    const dim = this._axisDim(axisId);
    const axis = this._axis(axisId);
    const [lo, hi] = this._axisRange(axisId);
    const c0 = this._axisCoord(axis, lo);
    const c1 = this._axisCoord(axis, hi);
    const c = this._axisCoord(axis, value);
    if (![c0, c1, c].every(Number.isFinite) || c1 === c0) return NaN;
    if (dim === "x") return this.plot.x + ((c - c0) / (c1 - c0)) * this.plot.w;
    return this.plot.y + (1 - (c - c0) / (c1 - c0)) * this.plot.h;
  }

  _listen(target, type, handler, options) {
    target.addEventListener(type, handler, options);
    this._listeners.push({ target, type, handler, options });
    return handler;
  }

  _interactionFlag(name, fallback = false) {
    const value = this.interaction && this.interaction[name];
    return value === undefined ? fallback : value === true;
  }

  _eventView(source = "view") {
    return {
      x0: this.view.x0,
      x1: this.view.x1,
      y0: this.view.y0,
      y1: this.view.y1,
      source,
    };
  }

  _dispatchChartEvent(name, detail) {
    if (!this.root || typeof CustomEvent !== "function") return;
    this.root.dispatchEvent(new CustomEvent(`fastcharts:${name}`, {
      detail,
      bubbles: true,
      composed: true,
    }));
  }

  _emitViewChange(source = "view", opts = {}) {
    const shouldDispatch = this._interactionFlag("view_change") || this._linkChannel;
    if (!shouldDispatch || this._destroyed) return;
    const broadcast = opts.broadcast !== false;
    this._pendingViewEvent = { source, broadcast };
    if (this._viewEventRaf) return;
    this._viewEventRaf = requestAnimationFrame(() => {
      this._viewEventRaf = null;
      const pending = this._pendingViewEvent || { source, broadcast };
      this._pendingViewEvent = null;
      const detail = this._eventView(pending.source);
      if (this._interactionFlag("view_change")) {
        this._dispatchChartEvent("view_change", detail);
      }
      if (this.comm && this._interactionFlag("view_change")) {
        this.comm.send({ type: "view_change", ...detail });
      }
      if (pending.broadcast) this._broadcastLinkedView(detail);
    });
  }

  _initLinkedCharts() {
    const group = this.interaction && this.interaction.link_group;
    if (!group || typeof BroadcastChannel !== "function") return;
    this._linkAxes = Array.isArray(this.interaction.link_axes)
      ? this.interaction.link_axes.filter((axis) => axis === "x" || axis === "y")
      : ["x", "y"];
    if (!this._linkAxes.length) this._linkAxes = ["x", "y"];
    this._linkChannel = new BroadcastChannel(`fastcharts:${group}`);
    this._linkChannel.onmessage = (event) => {
      const msg = event.data || {};
      if (!msg.view || msg.source === this._linkedSource) return;
      const next = { ...this.view };
      if (this._linkAxes.includes("x")) {
        next.x0 = Number(msg.view.x0);
        next.x1 = Number(msg.view.x1);
      }
      if (this._linkAxes.includes("y")) {
        next.y0 = Number(msg.view.y0);
        next.y1 = Number(msg.view.y1);
      }
      if (![next.x0, next.x1, next.y0, next.y1].every(Number.isFinite)) return;
      this._setView(next, { animate: false, source: "linked", broadcast: false });
    };
  }

  _broadcastLinkedView(detail) {
    if (!this._linkChannel) return;
    this._linkChannel.postMessage({ source: this._linkedSource, view: detail });
  }

  _applyClass(el, className) {
    if (typeof className !== "string") return;
    for (const token of className.split(/\s+/).filter(Boolean)) {
      try { el.classList.add(token); } catch (_) { /* Ignore invalid CSS class tokens. */ }
    }
  }

  _stylePropertyName(key) {
    if (key.startsWith("--")) return key;
    return key.replace(/[A-Z]/g, (match) => `-${match.toLowerCase()}`);
  }

  _stylePropertyValue(property, value) {
    if (typeof value !== "number") return String(value);
    if (!Number.isFinite(value)) return null;
    if (property.startsWith("--") || UNITLESS_STYLE_PROPS.has(property)) return String(value);
    return `${value}px`;
  }

  _applyStyle(el, style) {
    if (!style || typeof style !== "object" || Array.isArray(style)) return;
    for (const [key, value] of Object.entries(style)) {
      if (typeof key !== "string") continue;
      if (typeof value !== "string" && typeof value !== "number") continue;
      const property = this._stylePropertyName(key);
      const cssValue = this._stylePropertyValue(property, value);
      if (cssValue != null) el.style.setProperty(property, cssValue);
    }
  }

  _applySlot(el, slot) {
    const dom = this.spec.dom;
    if (!dom || typeof dom !== "object") return;
    if (slot === "root") this._applyClass(el, dom.class_name);
    if (dom.class_names && typeof dom.class_names === "object") {
      this._applyClass(el, dom.class_names[slot]);
    }
    if (slot === "root") this._applyStyle(el, dom.style);
    if (dom.styles && typeof dom.styles === "object") {
      this._applyStyle(el, dom.styles[slot]);
    }
  }

  _slotStyleValue(slot, property) {
    const styles = this.spec.dom?.styles;
    const style = styles && typeof styles === "object" ? styles[slot] : null;
    if (!style || typeof style !== "object" || Array.isArray(style)) return null;
    if (Object.prototype.hasOwnProperty.call(style, property)) return style[property];
    return null;
  }

  _syncContainerSize() {
    if (this._destroyed || !(this.fluid || this.fluidH) || !this.root) return;
    const rect = this.root.getBoundingClientRect();
    if (rect.width || rect.height) this._resize(rect.width, rect.height);
  }

  _armVisibilityResizeWatch() {
    if (!(this.fluid || this.fluidH)) return;
    const syncSoon = () => {
      if (this._destroyed) return;
      requestAnimationFrame(() => this._syncContainerSize());
    };
    this._listen(window, "resize", syncSoon);
    this._listen(window, "pageshow", syncSoon);
    this._listen(document, "visibilitychange", syncSoon);
    if (typeof IntersectionObserver !== "undefined") {
      this._io = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting || entry.intersectionRatio > 0)) {
          syncSoon();
        }
      });
      this._io.observe(this.root);
    }
  }

  _markStateValue(state, property, fallback = null) {
    const styles = this.markStyle && typeof this.markStyle === "object" ? this.markStyle[state] : null;
    if (!styles || typeof styles !== "object" || Array.isArray(styles)) return fallback;
    if (Object.prototype.hasOwnProperty.call(styles, property)) return styles[property];
    return fallback;
  }

  _markStateNumber(state, property, fallback) {
    const value = this._markStateValue(state, property, fallback);
    if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
    return value;
  }

  _markStatePaint(state, property, fallback) {
    const value = this._markStateValue(state, property, fallback);
    return typeof value === "string" ? value : fallback;
  }

  // DPR watch (renderer audit R7): browser zoom changes devicePixelRatio
  // without firing the ResizeObserver, leaving blurry backing stores. A
  // matchMedia resolution query fires exactly when dpr leaves its current
  // value; the handler re-derives backing stores and re-arms for the new dpr.
  _armDprWatch() {
    if (typeof window.matchMedia !== "function") return;
    this._dprMq?.removeEventListener?.("change", this._onDprChange);
    const mq = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`);
    this._onDprChange = () => {
      if (this._destroyed) return;
      this._resize(this.size.w, this.size.h); // re-reads devicePixelRatio
      this._armDprWatch();
    };
    mq.addEventListener?.("change", this._onDprChange, { once: true });
    this._dprMq = mq;
  }

  // GL context loss/restore (renderer audit R4): a backgrounded tab on a busy
  // GPU or a driver reset kills the context. preventDefault opts in to
  // restoration; on restore every GPU object is recreated from the retained
  // spec + payload, then a fresh view request re-syncs live tiers (kernel
  // updates written into now-dead buffers are gone until it answers).
  _initContextLossRecovery() {
    this._listen(this.canvas, "webglcontextlost", (e) => {
      e.preventDefault();
      this._glLost = true;
      if (this._raf) cancelAnimationFrame(this._raf);
      this._raf = null;
    });
    this._listen(this.canvas, "webglcontextrestored", () => {
      if (this._destroyed) return;
      this._glLost = false;
      // Old handles died with the context — drop them without delete calls.
      this._lutCache.clear();
      this.pickFbo = null;
      this.pickTex = null;
      try {
        this._initGl(this._payload);
      } catch (err) {
        this.root.textContent = "fastcharts: WebGL2 context could not be restored.";
        throw err;
      }
      this._scheduleViewRequest(this.view, { delay: 0 });
      this.draw();
    });
  }

  // Container size changed (fluid mode). Cheap on purpose: data GPU buffers
  // are untouched — the _map() uniforms absorb the new aspect — and the pick
  // FBO realloc is deferred to the next actual pick (_renderPick checks dims).
  // The view request re-decimates/re-bins at the new pixel size (§28), so a
  // bigger chart gains real detail, not just stretched pixels.
  _resize(cssW, cssH) {
    const w = this.fluid && cssW ? Math.max(120, Math.round(cssW)) : this.size.w;
    const h = this.fluidH && cssH ? Math.max(120, Math.round(cssH)) : this.size.h;
    // Browser zoom changes devicePixelRatio with no container resize (R7);
    // re-read it so backing stores stay crisp on a pure-DPR change too.
    const dpr = window.devicePixelRatio || 1;
    if (w === this.size.w && h === this.size.h && dpr === this.dpr) return;
    this.dpr = dpr;
    this.size.w = w;
    this.size.h = h;
    this._layout();
    const p = this.plot;
    this.canvas.style.width = p.w + "px";
    this.canvas.style.height = p.h + "px";
    this.canvas.width = p.w * this.dpr;
    this.canvas.height = p.h * this.dpr;
    this.chrome.style.width = this.size.w + "px";
    this.chrome.style.height = this.size.h + "px";
    this.chrome.width = this.size.w * this.dpr;
    this.chrome.height = this.size.h * this.dpr;
    if (
      this._legend &&
      this._slotStyleValue("legend", "max-height") == null &&
      this._slotStyleValue("legend", "maxHeight") == null
    ) {
      this._legend.style.maxHeight = p.h - 12 + "px";
    }
    this._pickDirty = true;
    this.draw();
    this._scheduleViewRequest();
  }

  _buildDom(el) {
    const s = this.spec;
    const root = document.createElement("div");
    root.className = "fastcharts";
    root.style.cssText =
      `position:relative;width:${this.fluid ? "100%" : this.size.w + "px"};` +
      `height:${this.fluidH ? "100%" : this.size.h + "px"};` +
      (this.fluidH ? "min-height:120px;" : "") + // parent without a height -> visible floor
      "font:12px system-ui,sans-serif;user-select:none;";
    this._applySlot(root, "root");
    el.appendChild(root);
    this.root = root;

    if (s.title) {
      const t = document.createElement("div");
      t.textContent = s.title;
      t.style.cssText =
        "position:absolute;top:6px;left:0;right:0;text-align:center;font-size:14px;font-weight:600;";
      this._applySlot(t, "title");
      root.appendChild(t);
    }

    this.chrome = document.createElement("canvas");
    this.chrome.style.cssText = "position:absolute;inset:0;pointer-events:none;";
    this._applySlot(this.chrome, "chrome");
    root.appendChild(this.chrome);

    this.canvas = document.createElement("canvas");
    this.canvas.style.cssText =
      `position:absolute;left:${this.plot.x}px;top:${this.plot.y}px;` +
      `width:${this.plot.w}px;height:${this.plot.h}px;cursor:crosshair;touch-action:none;`;
    this._applySlot(this.canvas, "canvas");
    root.appendChild(this.canvas);

    this.labels = document.createElement("div");
    this.labels.style.cssText = "position:absolute;inset:0;pointer-events:none;";
    this._applySlot(this.labels, "labels");
    root.appendChild(this.labels);

    // Hover tooltip (§17) — DOM, so it's crisp and selectable (§7).
    this.tooltip = document.createElement("div");
    this.tooltip.style.cssText =
      "position:absolute;display:none;pointer-events:none;z-index:5;" +
      "background:var(--chart-tooltip-bg, rgba(20,24,33,.92));" +
      "color:var(--chart-tooltip-text, #fff);padding:5px 8px;border-radius:4px;" +
      "font-size:11px;line-height:1.35;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,.3);";
    this._applySlot(this.tooltip, "tooltip");
    root.appendChild(this.tooltip);

    this._buildLegend(root);
  }

  _buildLegend(root) {
    const s = this.spec;
    if (s.show_legend === false) return;
    const items = [];
    for (const t of s.traces) {
      if (t.tier === "density") {
        items.push({ swatch: "gradient", cmap: t.density.colormap, name: t.name || "density" });
      } else if (t.color && t.color.mode === "categorical") {
        t.color.categories.forEach((cat, i) =>
          items.push({ swatch: t.color.palette[i], name: cat }));
      } else if (t.color && t.color.mode === "continuous") {
        items.push({ swatch: "gradient", cmap: t.color.colormap, name: t.name || "value" });
      } else if (t.name) {
        const c = (t.color && t.color.color) || (t.style && t.style.color);
        items.push({ swatch: c, name: t.name });
      }
    }
    if (!items.length) return;
    const lg = document.createElement("div");
    const rightInset = this.size.w - (this.plot.x + this.plot.w);
    lg.style.cssText =
      `position:absolute;top:${this.plot.y + 6}px;right:${rightInset + 6}px;` +
      "display:flex;flex-direction:column;gap:2px;font-size:11px;" +
      "background:var(--chart-legend-bg, rgba(128,128,128,.08));" +
      "border-radius:4px;padding:4px 8px;max-height:" +
      `${this.plot.h - 12}px;overflow:auto;`;
    this._applySlot(lg, "legend");
    for (const it of items) {
      const row = document.createElement("div");
      this._applySlot(row, "legend_item");
      const sw = document.createElement("span");
      let bg = it.swatch;
      if (it.swatch === "gradient") {
        const stops = COLORMAP_STOPS[it.cmap] || COLORMAP_STOPS.viridis;
        bg = `linear-gradient(90deg,${stops.map((c) => `rgb(${c[0]},${c[1]},${c[2]})`).join(",")})`;
        sw.style.background = bg;
      } else {
        sw.style.background = safeCssPaint(this.root, bg);
      }
      sw.style.cssText +=
        "display:inline-block;width:12px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px;";
      row.appendChild(sw);
      row.appendChild(document.createTextNode(it.name));
      lg.appendChild(row);
    }
    root.appendChild(lg);
    this._legend = lg; // _resize refreshes its max-height
  }

  _initGl(buffer) {
    const dpr = window.devicePixelRatio || 1;
    this.dpr = dpr;
    this.canvas.width = this.plot.w * dpr;
    this.canvas.height = this.plot.h * dpr;
    this.chrome.width = this.size.w * dpr;
    this.chrome.height = this.size.h * dpr;
    this.chrome.style.width = this.size.w + "px";
    this.chrome.style.height = this.size.h + "px";

    const gl = this.canvas.getContext("webgl2", {
      antialias: false, premultipliedAlpha: true, alpha: true,
    });
    if (!gl) {
      this.root.textContent = "fastcharts: WebGL2 unavailable in this browser.";
      throw new Error("webgl2 unavailable");
    }
    this.gl = gl;
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    this.pointProg = makeProgram(gl, POINT_VS, POINT_FS);
    this.lineProg = makeProgram(gl, LINE_VS, LINE_FS);
    this.areaProg = makeProgram(gl, AREA_VS, AREA_FS);
    this.rectProg = makeProgram(gl, RECT_VS, RECT_FS);
    this.barProg = makeProgram(gl, BAR_VS, RECT_FS);
    this.pickProg = makeProgram(gl, PICK_VS, PICK_FS);
    this.densityProg = makeProgram(gl, DENSITY_VS, DENSITY_FS);
    this.heatmapProg = makeProgram(gl, HEATMAP_VS, HEATMAP_FS);
    this._glPrograms = [
      this.pointProg, this.lineProg, this.areaProg, this.rectProg,
      this.barProg, this.pickProg, this.densityProg, this.heatmapProg,
    ];

    // Fullscreen quad for density.
    this.quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);

    this.gpuTraces = this.spec.traces.map((t) => this._buildTrace(buffer, t));
    this._pickable = this.gpuTraces.some((g) => markOf(g.trace.kind).pointPick && g.tier !== "density");
    if (this._pickable) this._initPickTarget();
  }

  _lut(name) {
    if (this._lutCache.has(name)) return this._lutCache.get(name);
    const gl = this.gl;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, buildLutData(name));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this._lutCache.set(name, tex);
    return tex;
  }

  _paletteLut(palette) {
    // Cached by palette identity: categorical drill updates request this per
    // zoom step, and an uncached texture per call is a steady GL leak.
    const key = "pal:" + palette.join(",");
    if (this._lutCache.has(key)) return this._lutCache.get(key);
    const gl = this.gl;
    const data = new Uint8Array(256 * 4);
    for (let i = 0; i < 256; i++) {
      const c = hexColor(palette[i % palette.length]);
      data[i * 4] = c[0] * 255;
      data[i * 4 + 1] = c[1] * 255;
      data[i * 4 + 2] = c[2] * 255;
      data[i * 4 + 3] = 255;
    }
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this._lutCache.set(key, tex);
    return tex;
  }

  _buildTrace(buffer, t) {
    const gl = this.gl;
    const g = {
      trace: t,
      tier: t.tier,
      color: [0.3, 0.47, 0.66, 1],
      xAxis: typeof t.x_axis === "string" ? t.x_axis : "x",
      yAxis: typeof t.y_axis === "string" ? t.y_axis : "y",
    };

    if (t.tier === "density") {
      const d = t.density;
      const grid = new Float32Array(buffer, this.spec.columns[d.buf].byte_offset, d.w * d.h);
      g.densityNormMax = d.max;
      g.density = {
        w: d.w, h: d.h, max: d.max, normMax: d.max, colormap: d.colormap,
        xRange: d.x_range, yRange: d.y_range,
        grid: lodCopyGrid(grid),
        tex: this._uploadGrid(grid, d.w, d.h, d.max),
        lut: this._lut(d.colormap),
      };
      g._shownDensity = g.density;
      lodRememberDensity(this, g, g.density);
      return g;
    }

    // Per-mark GPU setup is dispatched through MARK_KINDS (55_marks.js) so a
    // new chart kind is an entry in that registry, not another branch here.
    markOf(t.kind).build(this, g, t, buffer);
    return g;
  }

  // Shared (x,y) geometry setup for xy-shaped marks (scatter, line, area, …).
  // A mark whose geometry isn't a plain x/y pair (bars/candles have their own
  // vertex layout) skips this and uploads its own buffers in build().
  _buildXY(g, t, buffer) {
    const x = this._columnView(buffer, this.spec.columns[t.x]);
    const y = this._columnView(buffer, this.spec.columns[t.y]);
    g.xMeta = { ...this.spec.columns[t.x] };
    g.yMeta = { ...this.spec.columns[t.y] };
    g.n = Math.min(x.length, y.length);
    g._cpu = { x, y, xMeta: g.xMeta, yMeta: g.yMeta };
    g.xBuf = this._upload(x);
    g.yBuf = this._upload(y);
  }

  _buildScatterMark(g, t, buffer) {
    this._buildXY(g, t, buffer);
    g.colorMode = 0;
    g.color = parseColor(this.root, t.color && t.color.color, [0.3, 0.47, 0.66, 1]);
    if (t.color && t.color.mode === "continuous") {
      g.colorMode = 1;
      g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
      g.lut = this._lut(t.color.colormap);
    } else if (t.color && t.color.mode === "categorical") {
      g.colorMode = 2;
      g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
      g.lut = this._paletteLut(t.color.palette);
    }
    g.sizeMode = 0;
    g.size = (t.size && t.size.size) || 4.0;
    g.sizeRange = [2, 18];
    if (t.size && t.size.mode === "continuous") {
      g.sizeMode = 1;
      g.sBuf = this._upload(this._columnView(buffer, this.spec.columns[t.size.buf]));
      g.sizeRange = t.size.range_px;
    }
  }

  _buildLineMark(g, t, buffer) {
    this._buildXY(g, t, buffer);
    g.color = parseColor(this.root, t.style && t.style.color, [0.3, 0.47, 0.66, 1]);
  }

  _buildAreaMark(g, t, buffer) {
    this._buildXY(g, t, buffer);
    const base = this._columnView(buffer, this.spec.columns[t.base]);
    g.baseMeta = { ...this.spec.columns[t.base] };
    g.n = Math.min(g.n, base.length);
    if (g._cpu) g._cpu.base = base;
    g.baseBuf = this._upload(base);
    g.color = parseColor(this.root, t.style && t.style.color, [0.3, 0.47, 0.66, 1]);
    g.lineColor = parseColor(this.root, t.style && t.style.color, g.color);
  }

  _buildRectMark(g, t, buffer) {
    const x0 = this._columnView(buffer, this.spec.columns[t.x0]);
    const x1 = this._columnView(buffer, this.spec.columns[t.x1]);
    const y0 = this._columnView(buffer, this.spec.columns[t.y0]);
    const y1 = this._columnView(buffer, this.spec.columns[t.y1]);
    g.x0Meta = { ...this.spec.columns[t.x0] };
    g.x1Meta = { ...this.spec.columns[t.x1] };
    g.y0Meta = { ...this.spec.columns[t.y0] };
    g.y1Meta = { ...this.spec.columns[t.y1] };
    g.n = Math.min(x0.length, x1.length, y0.length, y1.length);
    g._cpuRect = {
      x0, x1, y0, y1,
      x0Meta: g.x0Meta, x1Meta: g.x1Meta, y0Meta: g.y0Meta, y1Meta: g.y1Meta,
    };
    g.x0Buf = this._upload(x0);
    g.x1Buf = this._upload(x1);
    g.y0Buf = this._upload(y0);
    g.y1Buf = this._upload(y1);
    g.color = parseColor(this.root, t.style && t.style.color, [0.3, 0.47, 0.66, 1]);
    g.colorMode = 0;
    if (t.color && t.color.mode === "continuous") {
      g.colorMode = 1;
      g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
      g.lut = this._lut(t.color.colormap);
    } else if (t.color && t.color.mode === "categorical") {
      g.colorMode = 2;
      g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
      g.lut = this._paletteLut(t.color.palette);
    }
  }

  _buildBarMark(g, t, buffer) {
    const b = t.bar;
    if (!b) return this._buildRectMark(g, t, buffer);
    const pos = this._columnView(buffer, this.spec.columns[b.pos]);
    const v1 = this._columnView(buffer, this.spec.columns[b.value1]);
    g.posMeta = { ...this.spec.columns[b.pos] };
    g.value1Meta = { ...this.spec.columns[b.value1] };
    g.n = Math.min(pos.length, v1.length);
    g.posBuf = this._upload(pos);
    g.value1Buf = this._upload(v1);
    g.orientation = b.orientation === "horizontal" ? 1 : 0;
    g.value0Const = b.value0_const ?? 0;
    g.value0Mode = b.value0 === undefined ? 0 : 1;
    g.width = b.width;
    if (g.value0Mode === 1) {
      const v0 = this._columnView(buffer, this.spec.columns[b.value0]);
      g.value0Meta = { ...this.spec.columns[b.value0] };
      g.n = Math.min(g.n, v0.length);
      g._cpuValue0 = v0;
      g.value0Buf = this._upload(v0);
    }
    g._cpu = g.orientation === 1
      ? { x: v1, y: pos, xMeta: g.value1Meta, yMeta: g.posMeta, value0: g._cpuValue0 }
      : { x: pos, y: v1, xMeta: g.posMeta, yMeta: g.value1Meta, value0: g._cpuValue0 };
    g.color = parseColor(this.root, t.style && t.style.color, [0.3, 0.47, 0.66, 1]);
    g.colorMode = 0;
    if (t.color && t.color.mode === "continuous") {
      g.colorMode = 1;
      g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
      g.lut = this._lut(t.color.colormap);
    } else if (t.color && t.color.mode === "categorical") {
      g.colorMode = 2;
      g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
      g.lut = this._paletteLut(t.color.palette);
    }
  }

  _buildHeatmapMark(g, t, buffer) {
    const h = t.heatmap;
    const grid = this._columnView(buffer, this.spec.columns[h.buf]);
    g.heatmap = {
      w: h.w,
      h: h.h,
      xRange: h.x_range,
      yRange: h.y_range,
      colormap: h.colormap,
      tex: this._uploadHeatmapGrid(grid, h.w, h.h),
      lut: this._lut(h.colormap),
    };
    g._cpuHeatmap = { grid };
  }

  _uploadGrid(f32, w, h, maxVal) {
    const gl = this.gl;
    const tex = gl.createTexture();
    lodWriteGridTexture(gl, tex, f32, w, h, maxVal);
    return tex;
  }

  _uploadHeatmapGrid(f32, w, h) {
    const gl = this.gl;
    const tex = gl.createTexture();
    const data = new Uint8Array(f32.length);
    for (let i = 0; i < f32.length; i++) {
      const v = f32[i];
      if (Number.isFinite(v)) {
        data[i] = Math.max(1, Math.min(255, Math.round(1 + 254 * Math.max(0, Math.min(1, v)))));
      }
    }
    gl.bindTexture(gl.TEXTURE_2D, tex);
    const align = gl.getParameter(gl.UNPACK_ALIGNMENT);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, w, h, 0, gl.RED, gl.UNSIGNED_BYTE, data);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, align);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return tex;
  }

  // Grid tone-mapping, exposure normalization, source cache, and the drill
  // lifecycle live in 45_lod.js — chart-agnostic so future tiered kinds
  // (heatmap, histogram) reuse them instead of copy-pasting.

  _columnView(buffer, meta) {
    return new Float32Array(buffer, meta.byte_offset, meta.len);
  }

  _upload(f32) {
    const gl = this.gl;
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, f32, gl.STATIC_DRAW);
    return buf;
  }

  _initPickTarget() {
    const gl = this.gl;
    this.pickTex = gl.createTexture();
    this._allocPickTex();
    this.pickFbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.pickFbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.pickTex, 0);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this._pickDirty = true;
  }

  _allocPickTex() {
    // Sized to the canvas backing store; called again lazily after a resize
    // (from _renderPick, not _resize — no FBO churn during a drag-resize).
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.pickTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, this.canvas.width, this.canvas.height, 0,
      gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    this._pickW = this.canvas.width;
    this._pickH = this.canvas.height;
  }

  // -- drawing --------------------------------------------------------------

  _map(meta, lo, hi, axisId = null) {
    if (!axisId) {
      const mul = 2 / ((hi - lo) * meta.scale);
      const add = ((meta.offset - lo) / (hi - lo)) * 2 - 1;
      return [mul, add];
    }
    const axis = this._axis(axisId);
    const c0 = this._axisCoord(axis, lo);
    const c1 = this._axisCoord(axis, hi);
    if (![c0, c1].every(Number.isFinite) || c1 === c0) return [0, -2];
    const mul = 2 / (c1 - c0);
    const add = -1 - c0 * mul;
    return [mul, add];
  }

  _mapConst(value, lo, hi, axisId = null) {
    if (!axisId) return ((value - lo) / (hi - lo)) * 2 - 1;
    const axis = this._axis(axisId);
    const c = this._axisCoord(axis, value);
    const c0 = this._axisCoord(axis, lo);
    const c1 = this._axisCoord(axis, hi);
    if (![c, c0, c1].every(Number.isFinite) || c1 === c0) return -2;
    return ((c - c0) / (c1 - c0)) * 2 - 1;
  }

  _edgePadForValue(value, lo, hi, pixels) {
    if (!Number.isFinite(value) || !Number.isFinite(lo) || !Number.isFinite(hi) || hi === lo) return 0;
    const span = Math.abs(hi - lo);
    const eps = span * 1e-10 + 1e-12;
    const px = Math.max(1, pixels || 1);
    const padPx = Math.max(2, Math.ceil(this.dpr || 1));
    if (Math.abs(value - lo) <= eps) return -(2 * padPx) / px;
    if (Math.abs(value - hi) <= eps) return (2 * padPx) / px;
    return 0;
  }

  _setAxisUniforms(prog, prefix, meta, axisId) {
    const gl = this.gl;
    const u = (n) => uniformOf(gl, prog, n);
    gl.uniform2f(u(`${prefix}meta`), meta && Number.isFinite(meta.offset) ? meta.offset : 0, meta && meta.scale ? meta.scale : 1);
    gl.uniform1i(u(`${prefix}mode`), this._axisMode(axisId));
  }

  draw() {
    if (this._destroyed) return;
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = null;
      if (this._destroyed) return;
      this._drawNow();
    });
  }


  _drawNow() {
    if (this._destroyed || !this.gl || this._glLost) return;
    const gl = this.gl;
    const { x0, x1, y0, y1 } = this.view;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    const bg = this.theme.bg;
    if (bg) gl.clearColor(bg[0] * bg[3], bg[1] * bg[3], bg[2] * bg[3], bg[3]);
    else gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);

    for (const g of this.gpuTraces) {
      if (g.tier === "density") {
        // Tier frame (drill/fades/cache) lives in 45_lod.js — chart-agnostic.
        const [gx0, gx1] = this._axisRange(g.xAxis);
        const [gy0, gy1] = this._axisRange(g.yAxis);
        lodDrawDensityTier(this, g, gx0, gx1, gy0, gy1);
        continue;
      }
      markOf(g.trace.kind).draw(this, g, x0, x1, y0, y1);
    }
    this._drawHoverState();
    this._pickDirty = true;
    this._drawChrome();
  }

  _bindScalarAttr(prog, name, buf, byteOffset, divisor) {
    const gl = this.gl;
    const loc = gl.getAttribLocation(prog, name);
    if (loc < 0) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 1, gl.FLOAT, false, 0, byteOffset);
    gl.vertexAttribDivisor(loc, divisor);
  }

  _disableAttr(prog, name) {
    const gl = this.gl;
    const loc = gl.getAttribLocation(prog, name);
    if (loc >= 0) gl.disableVertexAttribArray(loc);
  }

  _drawPoints(g, xm, ym, opacityScale = 1) {
    const gl = this.gl;
    const prog = this.pointProg;
    gl.useProgram(prog);
    const u = (n) => uniformOf(gl, prog, n);
    gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
    gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
    this._setAxisUniforms(prog, "u_x", g.xMeta, g.xAxis);
    this._setAxisUniforms(prog, "u_y", g.yMeta, g.yAxis);
    gl.uniform1f(u("u_dpr"), this.dpr);
    gl.uniform1f(u("u_size"), g.size);
    gl.uniform1i(u("u_sizeMode"), g.sizeMode);
    gl.uniform2f(u("u_sizeRange"), g.sizeRange[0], g.sizeRange[1]);
    gl.uniform1i(u("u_colorMode"), g.colorMode);
    gl.uniform1f(u("u_opacity"), (g.trace.style.opacity ?? 0.8) * opacityScale);
    gl.uniform1f(u("u_selectedOpacity"), this._markStateNumber("selected", "opacity", 1));
    gl.uniform1f(u("u_unselectedOpacity"), this._markStateNumber("unselected", "opacity", 0.12));
    const [r, gg, b] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, 1);

    this._bindScalarAttr(prog, "ax", g.xBuf, 0, 0);
    this._bindScalarAttr(prog, "ay", g.yBuf, 0, 0);
    if (g.colorMode !== 0 && g.cBuf) {
      this._bindScalarAttr(prog, "a_cval", g.cBuf, 0, 0);
    } else {
      this._disableAttr(prog, "a_cval");
      const loc = gl.getAttribLocation(prog, "a_cval");
      if (loc >= 0) gl.vertexAttrib1f(loc, 0);
    }
    if (g.sizeMode === 1 && g.sBuf) {
      this._bindScalarAttr(prog, "a_sval", g.sBuf, 0, 0);
    } else {
      this._disableAttr(prog, "a_sval");
      const loc = gl.getAttribLocation(prog, "a_sval");
      if (loc >= 0) gl.vertexAttrib1f(loc, 0.5);
    }
    gl.uniform1i(u("u_selActive"), g.selActive ? 1 : 0);
    if (g.selActive && g.selBuf) {
      this._bindScalarAttr(prog, "a_sel", g.selBuf, 0, 0);
    } else {
      this._disableAttr(prog, "a_sel");
      const loc = gl.getAttribLocation(prog, "a_sel");
      if (loc >= 0) gl.vertexAttrib1f(loc, 1.0);
    }
    if (g.lut) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, g.lut);
      gl.uniform1i(u("u_lut"), 0);
    }
    // Drill handoff (§5): blend from the density ramp toward native colors.
    // The shown weight eases toward the kernel's target so successive drill
    // updates recolor smoothly instead of stepping. Time-based decay (τ=90ms)
    // — a per-frame factor would converge 2.4× faster on a 144Hz display.
    const blendTarget = g.lodBlend ?? 0;
    let blend = g.lodBlendShown ?? blendTarget;
    if (Math.abs(blend - blendTarget) > 0.005 && !this._prefersReducedMotion()) {
      const now = performance.now();
      const dt = g._blendTick ? Math.min(100, now - g._blendTick) : 16;
      g._blendTick = now;
      blend += (blendTarget - blend) * (1 - Math.exp(-dt / 90));
      g.lodBlendShown = blend;
      this.draw();
    } else {
      g.lodBlendShown = blend = blendTarget;
      g._blendTick = 0;
    }
    gl.uniform1f(u("u_dblend"), blend);
    if (blend > 0.001 && g.dBuf && g.dlut) {
      this._bindScalarAttr(prog, "a_dval", g.dBuf, 0, 0);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, g.dlut);
      gl.uniform1i(u("u_dlut"), 1);
    } else {
      this._disableAttr(prog, "a_dval");
      const loc = gl.getAttribLocation(prog, "a_dval");
      if (loc >= 0) gl.vertexAttrib1f(loc, 0);
      gl.uniform1i(u("u_dlut"), 1); // sampler must still point at a valid unit
    }
    gl.drawArrays(gl.POINTS, 0, g.n);
  }

  _drawHoverState() {
    const hit = this._hoverTarget;
    if (!hit || !hit.g) return;
    const g = hit.g;
    if (g.trace.kind !== "scatter" || g.tier === "density") return;
    if (!Number.isInteger(hit.index) || hit.index < 0 || hit.index >= g.n) return;
    const [x0, x1] = this._axisRange(g.xAxis);
    const [y0, y1] = this._axisRange(g.yAxis);
    this._drawHoverPoint(
      g,
      hit.index,
      this._map(g.xMeta, x0, x1, g.xAxis),
      this._map(g.yMeta, y0, y1, g.yAxis)
    );
  }

  _drawHoverPoint(g, index, xm, ym) {
    const gl = this.gl;
    const prog = this.pointProg;
    gl.useProgram(prog);
    const u = (n) => uniformOf(gl, prog, n);
    gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
    gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
    this._setAxisUniforms(prog, "u_x", g.xMeta, g.xAxis);
    this._setAxisUniforms(prog, "u_y", g.yMeta, g.yAxis);
    const defaultSize = Math.max((g.size || 4) * 1.75, (g.size || 4) + 5);
    const size = Math.max(0, this._markStateNumber("hover", "size", defaultSize));
    const opacity = Math.max(0, Math.min(1, this._markStateNumber("hover", "opacity", 0.95)));
    const color = parseColor(
      this.root,
      this._markStatePaint("hover", "color", "rgba(15,23,42,.92)"),
      [0.06, 0.09, 0.16, 0.92]
    );
    gl.uniform1f(u("u_dpr"), this.dpr);
    gl.uniform1f(u("u_size"), size);
    gl.uniform1i(u("u_sizeMode"), 0);
    gl.uniform2f(u("u_sizeRange"), size, size);
    gl.uniform1i(u("u_colorMode"), 0);
    gl.uniform1f(u("u_opacity"), opacity);
    gl.uniform1f(u("u_selectedOpacity"), 1);
    gl.uniform1f(u("u_unselectedOpacity"), 1);
    gl.uniform4f(u("u_color"), color[0], color[1], color[2], 1);
    gl.uniform1i(u("u_selActive"), 0);
    gl.uniform1f(u("u_dblend"), 0);

    this._bindScalarAttr(prog, "ax", g.xBuf, 0, 0);
    this._bindScalarAttr(prog, "ay", g.yBuf, 0, 0);
    for (const [name, value] of [["a_cval", 0], ["a_sval", 0.5], ["a_sel", 1], ["a_dval", 0]]) {
      this._disableAttr(prog, name);
      const loc = gl.getAttribLocation(prog, name);
      if (loc >= 0) gl.vertexAttrib1f(loc, value);
    }
    gl.drawArrays(gl.POINTS, index, 1);
  }

  _drawDensity(g, density, opacityScale = 1) {
    const gl = this.gl;
    const prog = this.densityProg;
    gl.useProgram(prog);
    const u = (n) => uniformOf(gl, prog, n);
    const { x0, x1, y0, y1 } = this.view;
    const [vx0, vx1] = this._axisRange(g.xAxis);
    const [vy0, vy1] = this._axisRange(g.yAxis);
    gl.uniform4f(u("u_view"), vx0 ?? x0, vx1 ?? x1, vy0 ?? y0, vy1 ?? y1);
    gl.uniform1i(u("u_xmode"), this._axisMode(g.xAxis));
    gl.uniform1i(u("u_ymode"), this._axisMode(g.yAxis));
    const d = density || g.density;
    gl.uniform4f(u("u_gridRange"), d.xRange[0], d.xRange[1], d.yRange[0], d.yRange[1]);
    gl.uniform1f(u("u_opacity"), (g.trace.style.opacity ?? 1.0) * opacityScale);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, d.tex);
    gl.uniform1i(u("u_grid"), 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, d.lut);
    gl.uniform1i(u("u_lut"), 1);
    const loc = gl.getAttribLocation(prog, "a_corner");
    const maxAttrs = gl.getParameter(gl.MAX_VERTEX_ATTRIBS);
    for (let i = 0; i < maxAttrs; i++) gl.disableVertexAttribArray(i);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(loc, 0);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  _drawHeatmap(g) {
    const h = g.heatmap;
    if (!h) return;
    const gl = this.gl;
    const prog = this.heatmapProg;
    gl.useProgram(prog);
    const u = (n) => uniformOf(gl, prog, n);
    const { x0, x1, y0, y1 } = this.view;
    const [vx0, vx1] = this._axisRange(g.xAxis);
    const [vy0, vy1] = this._axisRange(g.yAxis);
    gl.uniform4f(u("u_view"), vx0 ?? x0, vx1 ?? x1, vy0 ?? y0, vy1 ?? y1);
    gl.uniform1i(u("u_xmode"), this._axisMode(g.xAxis));
    gl.uniform1i(u("u_ymode"), this._axisMode(g.yAxis));
    gl.uniform4f(u("u_gridRange"), h.xRange[0], h.xRange[1], h.yRange[0], h.yRange[1]);
    gl.uniform1f(u("u_opacity"), g.trace.style.opacity ?? 1.0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, h.tex);
    gl.uniform1i(u("u_grid"), 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, h.lut);
    gl.uniform1i(u("u_lut"), 1);
    const loc = gl.getAttribLocation(prog, "a_corner");
    const maxAttrs = gl.getParameter(gl.MAX_VERTEX_ATTRIBS);
    for (let i = 0; i < maxAttrs; i++) gl.disableVertexAttribArray(i);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(loc, 0);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  _drawLine(g, xm, ym, color = null, width = null, opacity = null) {
    if (g.n < 2) return;
    const gl = this.gl;
    gl.useProgram(this.lineProg);
    const u = (n) => uniformOf(gl, this.lineProg, n);
    gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
    gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
    this._setAxisUniforms(this.lineProg, "u_x", g.xMeta, g.xAxis);
    this._setAxisUniforms(this.lineProg, "u_y", g.yMeta, g.yAxis);
    gl.uniform2f(u("u_res"), this.canvas.width, this.canvas.height);
    gl.uniform1f(u("u_width"), (width ?? g.trace.style.width ?? 1.5) * this.dpr);
    const [r, gg, b, a] = color || g.color;
    gl.uniform4f(u("u_color"), r, gg, b, a * (opacity ?? g.trace.style.opacity ?? 1));
    this._bindScalarAttr(this.lineProg, "ax0", g.xBuf, 0, 1);
    this._bindScalarAttr(this.lineProg, "ax1", g.xBuf, 4, 1);
    this._bindScalarAttr(this.lineProg, "ay0", g.yBuf, 0, 1);
    this._bindScalarAttr(this.lineProg, "ay1", g.yBuf, 4, 1);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n - 1);
  }

  _drawArea(g, xm, ym, bm) {
    if (g.n < 2) return;
    const gl = this.gl;
    const prog = this.areaProg;
    gl.useProgram(prog);
    const u = (n) => uniformOf(gl, prog, n);
    gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
    gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
    gl.uniform2f(u("u_bmap"), bm[0], bm[1]);
    this._setAxisUniforms(prog, "u_x", g.xMeta, g.xAxis);
    this._setAxisUniforms(prog, "u_y", g.yMeta, g.yAxis);
    this._setAxisUniforms(prog, "u_b", g.baseMeta, g.yAxis);
    const [r, gg, b, a] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, a * (g.trace.style.opacity ?? 0.35));
    this._bindScalarAttr(prog, "ax0", g.xBuf, 0, 1);
    this._bindScalarAttr(prog, "ax1", g.xBuf, 4, 1);
    this._bindScalarAttr(prog, "ay0", g.yBuf, 0, 1);
    this._bindScalarAttr(prog, "ay1", g.yBuf, 4, 1);
    this._bindScalarAttr(prog, "ab0", g.baseBuf, 0, 1);
    this._bindScalarAttr(prog, "ab1", g.baseBuf, 4, 1);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n - 1);
  }

  _drawRects(g, x0, x1, y0, y1, edgePad = [0, 0, 0, 0]) {
    if (!g.n) return;
    const gl = this.gl;
    const prog = this.rectProg;
    gl.useProgram(prog);
    const u = (n) => uniformOf(gl, prog, n);
    gl.uniform2f(u("u_x0map"), x0[0], x0[1]);
    gl.uniform2f(u("u_x1map"), x1[0], x1[1]);
    gl.uniform2f(u("u_y0map"), y0[0], y0[1]);
    gl.uniform2f(u("u_y1map"), y1[0], y1[1]);
    this._setAxisUniforms(prog, "u_x0", g.x0Meta, g.xAxis);
    this._setAxisUniforms(prog, "u_x1", g.x1Meta, g.xAxis);
    this._setAxisUniforms(prog, "u_y0", g.y0Meta, g.yAxis);
    this._setAxisUniforms(prog, "u_y1", g.y1Meta, g.yAxis);
    gl.uniform1i(u("u_xmode"), this._axisMode(g.xAxis));
    gl.uniform1i(u("u_ymode"), this._axisMode(g.yAxis));
    gl.uniform4f(u("u_edgePad"), edgePad[0], edgePad[1], edgePad[2], edgePad[3]);
    const [r, gg, b, a] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, a * (g.trace.style.opacity ?? 1));
    gl.uniform1i(u("u_colorMode"), g.colorMode || 0);
    this._bindScalarAttr(prog, "ax0", g.x0Buf, 0, 1);
    this._bindScalarAttr(prog, "ax1", g.x1Buf, 0, 1);
    this._bindScalarAttr(prog, "ay0", g.y0Buf, 0, 1);
    this._bindScalarAttr(prog, "ay1", g.y1Buf, 0, 1);
    if (g.colorMode && g.cBuf) {
      this._bindScalarAttr(prog, "a_cval", g.cBuf, 0, 1);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, g.lut);
      gl.uniform1i(u("u_lut"), 0);
    } else {
      this._disableAttr(prog, "a_cval");
      const loc = gl.getAttribLocation(prog, "a_cval");
      if (loc >= 0) gl.vertexAttrib1f(loc, 0);
    }
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n);
  }

  _drawBars(g, pmap, v1map, v0map, v0Const, v0EdgePad = 0) {
    if (!g.n) return;
    const gl = this.gl;
    const prog = this.barProg;
    gl.useProgram(prog);
    const u = (n) => uniformOf(gl, prog, n);
    gl.uniform2f(u("u_pmap"), pmap[0], pmap[1]);
    gl.uniform2f(u("u_v1map"), v1map[0], v1map[1]);
    gl.uniform2f(u("u_v0map"), v0map ? v0map[0] : 1, v0map ? v0map[1] : 0);
    const pAxis = g.orientation === 1 ? g.yAxis : g.xAxis;
    const vAxis = g.orientation === 1 ? g.xAxis : g.yAxis;
    this._setAxisUniforms(prog, "u_p", g.posMeta, pAxis);
    this._setAxisUniforms(prog, "u_v1", g.value1Meta, vAxis);
    this._setAxisUniforms(prog, "u_v0", g.value0Meta, vAxis);
    gl.uniform1i(u("u_pmode"), this._axisMode(pAxis));
    gl.uniform1i(u("u_vmode"), this._axisMode(vAxis));
    gl.uniform1f(u("u_width"), g.width);
    gl.uniform1i(u("u_orientation"), g.orientation);
    gl.uniform1i(u("u_v0Mode"), g.value0Mode);
    gl.uniform1f(u("u_v0Const"), v0Const ?? 0);
    gl.uniform1f(u("u_v0EdgePad"), v0EdgePad);
    const [r, gg, b, a] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, a * (g.trace.style.opacity ?? 1));
    gl.uniform1i(u("u_colorMode"), g.colorMode || 0);
    this._bindScalarAttr(prog, "a_pos", g.posBuf, 0, 1);
    this._bindScalarAttr(prog, "a_v1", g.value1Buf, 0, 1);
    if (g.value0Mode === 1 && g.value0Buf) {
      this._bindScalarAttr(prog, "a_v0", g.value0Buf, 0, 1);
    } else {
      this._disableAttr(prog, "a_v0");
      const loc = gl.getAttribLocation(prog, "a_v0");
      if (loc >= 0) gl.vertexAttrib1f(loc, 0);
    }
    if (g.colorMode && g.cBuf) {
      this._bindScalarAttr(prog, "a_cval", g.cBuf, 0, 1);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, g.lut);
      gl.uniform1i(u("u_lut"), 0);
    } else {
      this._disableAttr(prog, "a_cval");
      const loc = gl.getAttribLocation(prog, "a_cval");
      if (loc >= 0) gl.vertexAttrib1f(loc, 0);
    }
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n);
  }

  _dataPxX(value) {
    return this._dataPx("x", value);
  }

  _dataPxY(value) {
    return this._dataPx("y", value);
  }

  _styleNumber(style, key, fallback) {
    if (!style || typeof style !== "object") return fallback;
    const value = Number(style[key]);
    return Number.isFinite(value) ? value : fallback;
  }

  _axisStyleNumber(axis, key, fallback) {
    return this._styleNumber(axis && axis.style, key, fallback);
  }

  _axisStylePaint(axis, key, fallback) {
    const style = axis && typeof axis.style === "object" ? axis.style : null;
    return safeCssPaint(this.root, style && style[key], fallback);
  }

  _axisLabelCss(axis, dim, fallbackCss) {
    const rawPosition = axis && axis.label_position;
    const hasPosition = rawPosition !== undefined && rawPosition !== null;
    const hasOffset = axis && Number.isFinite(Number(axis.label_offset));
    const hasAngle = axis && Number.isFinite(Number(axis.label_angle));
    if (!hasPosition && !hasOffset && !hasAngle) return { css: fallbackCss, style: null };
    if (rawPosition && typeof rawPosition === "object" && !Array.isArray(rawPosition)) {
      return { css: "font-weight:500;white-space:nowrap;", style: rawPosition };
    }

    const p = this.plot;
    const position = String(hasPosition ? rawPosition : "center").replace(/-/g, "_");
    const inside = position.startsWith("inside_");
    const anchor = inside ? position.slice("inside_".length) : position;
    const offset = hasOffset ? Number(axis.label_offset) : 0;
    const side = axis && axis.side;
    const anchorFrac = anchor === "start" ? 0 : (anchor === "end" ? 1 : 0.5);

    if (dim === "x") {
      const x = p.x + p.w * anchorFrac;
      const outsideY = side === "top" ? p.y - 34 : p.y + p.h + 24;
      const insideY = side === "top" ? p.y + 12 : p.y + p.h - 12;
      const y = (inside ? insideY : outsideY) +
        (side === "top" ? (inside ? offset : -offset) : (inside ? -offset : offset));
      const translateX = anchor === "start" ? 0 : (anchor === "end" ? -100 : -50);
      const angle = hasAngle ? Number(axis.label_angle) : 0;
      return {
        css:
          `left:${x}px;top:${y}px;` +
          `transform:translateX(${translateX}%) rotate(${angle}deg);` +
          "transform-origin:center;font-weight:500;white-space:nowrap;",
        style: null,
      };
    }

    const xOutside = side === "right" ? p.x + p.w + 40 : 10;
    const xInside = side === "right" ? p.x + p.w - 12 : p.x + 12;
    const x = (inside ? xInside : xOutside) +
      (side === "right" ? (inside ? -offset : offset) : (inside ? offset : -offset));
    const y = p.y + p.h * (1 - anchorFrac);
    const angle = hasAngle ? Number(axis.label_angle) : (side === "right" ? 90 : -90);
    return {
      css:
        `left:${x}px;top:${y}px;` +
        `transform:translate(-50%,-50%) rotate(${angle}deg);` +
        "transform-origin:center;font-weight:500;white-space:nowrap;",
      style: null,
    };
  }

  _annotationPaint(style, fallback) {
    return safeCssPaint(this.root, style && style.color, fallback);
  }

  _drawArrowLine(ctx, x0, y0, x1, y1, style) {
    if (![x0, y0, x1, y1].every(Number.isFinite)) return;
    const angle = Math.atan2(y1 - y0, x1 - x0);
    const head = Math.max(7, this._styleNumber(style, "head_size", 8));
    ctx.save();
    ctx.globalAlpha = this._styleNumber(style, "opacity", 1);
    ctx.strokeStyle = this._annotationPaint(style, [0.4, 0.44, 0.52, 1]);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.lineWidth = Math.max(0.5, this._styleNumber(style, "width", 1.5));
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(
      x1 - head * Math.cos(angle - Math.PI / 6),
      y1 - head * Math.sin(angle - Math.PI / 6)
    );
    ctx.lineTo(
      x1 - head * Math.cos(angle + Math.PI / 6),
      y1 - head * Math.sin(angle + Math.PI / 6)
    );
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  _drawAnnotationShapes(ctx) {
    const annotations = Array.isArray(this.spec.annotations) ? this.spec.annotations : [];
    if (!annotations.length) return;
    const p = this.plot;
    ctx.save();
    ctx.beginPath();
    ctx.rect(p.x, p.y, p.w, p.h);
    ctx.clip();
    for (const ann of annotations) {
      const style = ann && typeof ann.style === "object" ? ann.style : {};
      if (ann.kind === "band") {
        const vertical = ann.axis === "x";
        const a = vertical ? this._dataPxX(Number(ann.start)) : this._dataPxY(Number(ann.start));
        const b = vertical ? this._dataPxX(Number(ann.end)) : this._dataPxY(Number(ann.end));
        if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
        const lo = Math.max(vertical ? p.x : p.y, Math.min(a, b));
        const hi = Math.min(vertical ? p.x + p.w : p.y + p.h, Math.max(a, b));
        if (hi <= lo) continue;
        ctx.save();
        ctx.globalAlpha = this._styleNumber(style, "opacity", 0.14);
        ctx.fillStyle = this._annotationPaint(style, [0.39, 0.45, 0.55, 1]);
        if (vertical) ctx.fillRect(lo, p.y, hi - lo, p.h);
        else ctx.fillRect(p.x, lo, p.w, hi - lo);
        ctx.restore();
      } else if (ann.kind === "rule") {
        const vertical = ann.axis === "x";
        const pos = vertical ? this._dataPxX(Number(ann.value)) : this._dataPxY(Number(ann.value));
        if (!Number.isFinite(pos)) continue;
        if (vertical && (pos < p.x - 1 || pos > p.x + p.w + 1)) continue;
        if (!vertical && (pos < p.y - 1 || pos > p.y + p.h + 1)) continue;
        const crisp = Math.round(pos) + 0.5;
        ctx.save();
        ctx.globalAlpha = this._styleNumber(style, "opacity", 1);
        ctx.strokeStyle = this._annotationPaint(style, [0.4, 0.44, 0.52, 1]);
        ctx.lineWidth = Math.max(0.5, this._styleNumber(style, "width", 1.5));
        ctx.beginPath();
        if (vertical) {
          ctx.moveTo(crisp, p.y);
          ctx.lineTo(crisp, p.y + p.h);
        } else {
          ctx.moveTo(p.x, crisp);
          ctx.lineTo(p.x + p.w, crisp);
        }
        ctx.stroke();
        ctx.restore();
      } else if (ann.kind === "arrow") {
        this._drawArrowLine(
          ctx,
          this._dataPxX(Number(ann.x0)),
          this._dataPxY(Number(ann.y0)),
          this._dataPxX(Number(ann.x1)),
          this._dataPxY(Number(ann.y1)),
          style
        );
      } else if (ann.kind === "callout") {
        const px = this._dataPxX(Number(ann.x));
        const py = this._dataPxY(Number(ann.y));
        const dx = Number.isFinite(Number(ann.dx)) ? Number(ann.dx) : 0;
        const dy = Number.isFinite(Number(ann.dy)) ? Number(ann.dy) : 0;
        this._drawArrowLine(ctx, px + dx, py + dy, px, py, style);
      }
    }
    ctx.restore();
  }

  _drawAnnotationLabels(updateLabels) {
    if (!updateLabels) return;
    const annotations = Array.isArray(this.spec.annotations) ? this.spec.annotations : [];
    if (!annotations.length) return;
    const p = this.plot;
    for (const ann of annotations) {
      const text = typeof ann.text === "string" ? ann.text : "";
      if (!text) continue;
      const style = ann && typeof ann.style === "object" ? ann.style : {};
      let px = null;
      let py = null;
      if (ann.kind === "text") {
        px = this._dataPxX(Number(ann.x));
        py = this._dataPxY(Number(ann.y));
      } else if (ann.kind === "rule") {
        if (ann.axis === "x") {
          px = this._dataPxX(Number(ann.value));
          py = p.y + 6;
        } else {
          px = p.x + p.w - 6;
          py = this._dataPxY(Number(ann.value));
        }
      } else if (ann.kind === "band") {
        if (ann.axis === "x") {
          px = (this._dataPxX(Number(ann.start)) + this._dataPxX(Number(ann.end))) / 2;
          py = p.y + 6;
        } else {
          px = p.x + p.w - 6;
          py = (this._dataPxY(Number(ann.start)) + this._dataPxY(Number(ann.end))) / 2;
        }
      } else if (ann.kind === "arrow") {
        px = (this._dataPxX(Number(ann.x0)) + this._dataPxX(Number(ann.x1))) / 2;
        py = (this._dataPxY(Number(ann.y0)) + this._dataPxY(Number(ann.y1))) / 2;
      } else if (ann.kind === "callout") {
        px = this._dataPxX(Number(ann.x));
        py = this._dataPxY(Number(ann.y));
      }
      if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
      if (px < p.x - 24 || px > p.x + p.w + 24 || py < p.y - 24 || py > p.y + p.h + 24) {
        continue;
      }
      const d = document.createElement("div");
      d.textContent = text;
      const dx = Number.isFinite(Number(ann.dx)) ? Number(ann.dx) : 0;
      const dy = Number.isFinite(Number(ann.dy)) ? Number(ann.dy) : 0;
      const anchor = ann.anchor === "middle" ? "-50%" : ann.anchor === "end" ? "-100%" : "0";
      d.style.cssText =
        `position:absolute;left:${px + dx}px;top:${py + dy}px;` +
        `transform:translate(${anchor},0);pointer-events:none;` +
        `color:${this._annotationPaint(style, this.theme.label)};` +
        "font-size:11px;line-height:1.2;font-weight:500;";
      this._applyClass(d, ann.class_name);
      this._applyStyle(d, style);
      this.labels.appendChild(d);
    }
  }

  _drawChrome() {
    const s = this.spec;
    const dpr = this.dpr;
    const ctx = this.chrome.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, this.size.w, this.size.h);
    const now = performance.now();
    const labelCadenceMs = this._viewAnim ? 80 : 0;
    const updateLabels = labelCadenceMs === 0
      || this._lastLabelDraw === null
      || now - this._lastLabelDraw >= labelCadenceMs;
    if (updateLabels) {
      this.labels.textContent = "";
      this._lastLabelDraw = now;
    }

    const p = this.plot;
    const xAxis = this._axis("x");
    const yAxis = this._axis("y");
    const xt = this._axisTicks("x", Math.max(3, p.w / (xAxis.kind === "time" ? 90 : 80)));
    const yt = this._axisTicks("y", Math.max(3, p.h / 45));
    const xEdge = (px) => Math.min(p.x + p.w - 0.5, Math.max(p.x + 0.5, Math.round(px) + 0.5));
    const yEdge = (py) => Math.min(p.y + p.h - 0.5, Math.max(p.y + 0.5, Math.round(py) + 0.5));

    ctx.strokeStyle = this._axisStylePaint(xAxis, "grid_color", this.theme.grid);
    ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(xAxis, "grid_width", 1));
    ctx.beginPath();
    for (const v of xt.ticks) {
      const px = this._dataPx("x", v);
      if (!Number.isFinite(px)) continue;
      const x = xEdge(px);
      ctx.moveTo(x, p.y);
      ctx.lineTo(x, p.y + p.h);
    }
    ctx.stroke();

    ctx.strokeStyle = this._axisStylePaint(yAxis, "grid_color", this.theme.grid);
    ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(yAxis, "grid_width", 1));
    ctx.beginPath();
    for (const v of yt.ticks) {
      const py = this._dataPx("y", v);
      if (!Number.isFinite(py)) continue;
      const y = yEdge(py);
      ctx.moveTo(p.x, y);
      ctx.lineTo(p.x + p.w, y);
    }
    ctx.stroke();

    this._drawAnnotationShapes(ctx);

    ctx.strokeStyle = this._axisStylePaint(yAxis, "axis_color", this.theme.axis);
    ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(yAxis, "axis_width", 1));
    ctx.beginPath();
    const yAxisX = yAxis.side === "right" ? p.x + p.w - 0.5 : p.x + 0.5;
    ctx.moveTo(yAxisX, p.y);
    ctx.lineTo(yAxisX, p.y + p.h - 0.5);
    ctx.stroke();

    ctx.strokeStyle = this._axisStylePaint(xAxis, "axis_color", this.theme.axis);
    ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(xAxis, "axis_width", 1));
    ctx.beginPath();
    const xAxisY = xAxis.side === "top" ? p.y + 0.5 : p.y + p.h - 0.5;
    ctx.moveTo(p.x, xAxisY);
    ctx.lineTo(p.x + p.w, xAxisY);
    ctx.stroke();

    for (const axis of Object.values(this.axes)) {
      if (!axis || axis.id === "y" || !String(axis.id || "").startsWith("y")) continue;
      ctx.strokeStyle = this._axisStylePaint(axis, "axis_color", this.theme.axis);
      ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(axis, "axis_width", 1));
      ctx.beginPath();
      const x = axis.side === "left" ? p.x + 0.5 : p.x + p.w + 0.5;
      ctx.moveTo(x, p.y);
      ctx.lineTo(x, p.y + p.h - 0.5);
      ctx.stroke();
    }

    const label = (text, css, axis, kind = "tick", extraStyle = null) => {
      if (!updateLabels) return;
      const d = document.createElement("div");
      d.textContent = text;
      const colorKey = kind === "label" ? "label_color" : "tick_color";
      const sizeKey = kind === "label" ? "label_size" : "tick_size";
      const defaultSize = kind === "label" ? 12 : 11;
      d.style.cssText =
        `position:absolute;color:${this._axisStylePaint(axis, colorKey, this.theme.label)};` +
        `font-size:${Math.max(8, this._axisStyleNumber(axis, sizeKey, defaultSize))}px;` +
        "line-height:1.2;" + css;
      this._applyStyle(d, extraStyle);
      this.labels.appendChild(d);
    };
    for (const v of (xt.labels || xt.ticks)) {
      const px = this._dataPx("x", v);
      if (px < p.x - 1 || px > p.x + p.w + 1) continue;
      const text = fmtAxis(xAxis, v, xt.step);
      const top = xAxis.side === "top" ? p.y - 18 : p.y + p.h + 6;
      label(text, `left:${px}px;top:${top}px;transform:translateX(-50%);`, xAxis);
    }
    for (const v of (yt.labels || yt.ticks)) {
      const py = this._dataPx("y", v);
      if (py < p.y - 1 || py > p.y + p.h + 1) continue;
      const text = fmtAxis(yAxis, v, yt.step);
      const css = yAxis.side === "right"
        ? `left:${p.x + p.w + 8}px;top:${py}px;transform:translateY(-50%);`
        : `right:${this.size.w - p.x + 8}px;top:${py}px;transform:translateY(-50%);`;
      label(text, css, yAxis);
    }
    for (const axis of Object.values(this.axes)) {
      if (!axis || axis.id === "y" || !String(axis.id || "").startsWith("y")) continue;
      const ticks = this._axisTicks(axis.id, Math.max(3, p.h / 45));
      for (const v of (ticks.labels || ticks.ticks)) {
        const py = this._dataPx(axis.id, v);
        if (py < p.y - 1 || py > p.y + p.h + 1) continue;
        const text = fmtAxis(axis, v, ticks.step);
        const css = axis.side === "left"
          ? `right:${this.size.w - p.x + 8}px;top:${py}px;transform:translateY(-50%);`
          : `left:${p.x + p.w + 8}px;top:${py}px;transform:translateY(-50%);`;
        label(text, css, axis);
      }
      if (axis.label) {
        const fallbackCss = axis.side === "left"
          ? `left:10px;top:${p.y + p.h / 2}px;transform:rotate(-90deg) translateX(50%);transform-origin:left;font-weight:500;`
          : `left:${p.x + p.w + 40}px;top:${p.y + p.h / 2}px;transform:rotate(90deg) translateX(-50%);transform-origin:left;font-weight:500;`;
        const placement = this._axisLabelCss(axis, "y", fallbackCss);
        label(axis.label, placement.css, axis, "label", placement.style);
      }
    }
    if (s.x_axis.label) {
      const top = xAxis.side === "top" ? p.y - 34 : p.y + p.h + 24;
      const fallbackCss = `left:${p.x + p.w / 2}px;top:${top}px;transform:translateX(-50%);font-weight:500;`;
      const placement = this._axisLabelCss(xAxis, "x", fallbackCss);
      label(s.x_axis.label, placement.css, xAxis, "label", placement.style);
    }
    if (s.y_axis.label) {
      const fallbackCss = yAxis.side === "right"
        ? `left:${p.x + p.w + 40}px;top:${p.y + p.h / 2}px;transform:rotate(90deg) translateX(-50%);transform-origin:left;font-weight:500;`
        : `left:10px;top:${p.y + p.h / 2}px;transform:rotate(-90deg) translateX(50%);transform-origin:left;font-weight:500;`;
      const placement = this._axisLabelCss(yAxis, "y", fallbackCss);
      label(s.y_axis.label, placement.css, yAxis, "label", placement.style);
    }
    this._drawAnnotationLabels(updateLabels);
  }

  _transitionActive() {
    const activeStart = (v) => v !== undefined && v !== null;
    return !!this._viewAnim || this.gpuTraces.some((g) =>
      activeStart(g._densityFadeStart) ||
      activeStart(g._densitySwitchFadeStart) ||
      activeStart(g._drillFadeStart) ||
      activeStart(g._drillExitFadeStart) ||
      !!g._densityNormAnim);
  }

  // -- picking (§17) --------------------------------------------------------

  _renderPick() {
    const gl = this.gl;
    if (this._pickW !== this.canvas.width || this._pickH !== this.canvas.height) {
      this._allocPickTex(); // deferred resize catch-up
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.pickFbo);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.disable(gl.BLEND);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    const { x0, x1, y0, y1 } = this.view;
    const prog = this.pickProg;
    gl.useProgram(prog);
    const u = (n) => uniformOf(gl, prog, n);
    gl.uniform1f(u("u_dpr"), this.dpr);
    let slot = 0;
    for (const g of this.gpuTraces) {
      // Density traces pick only while drilled to points (§5); the drill
      // sibling carries the buffers, the host g keeps the slot → trace id.
      const pg = g.tier === "density"
        ? (g.drill && !g._drillDying && this._viewInside(g.drill.win) ? g.drill : null)
        : (markOf(g.trace.kind).pointPick ? g : null);
      if (!pg || !pg.n) { g.pickSlot = -1; continue; } // stale slots must not alias
      const [px0, px1] = this._axisRange(pg.xAxis || g.xAxis);
      const [py0, py1] = this._axisRange(pg.yAxis || g.yAxis);
      const xm = this._map(pg.xMeta, px0, px1, pg.xAxis || g.xAxis);
      const ym = this._map(pg.yMeta, py0, py1, pg.yAxis || g.yAxis);
      gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
      gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
      this._setAxisUniforms(prog, "u_x", pg.xMeta, pg.xAxis || g.xAxis);
      this._setAxisUniforms(prog, "u_y", pg.yMeta, pg.yAxis || g.yAxis);
      gl.uniform1f(u("u_size"), pg.size);
      gl.uniform1i(u("u_sizeMode"), pg.sizeMode);
      gl.uniform2f(u("u_sizeRange"), pg.sizeRange[0], pg.sizeRange[1]);
      gl.uniform1i(u("u_slot"), slot);
      g.pickSlot = slot;
      this._bindScalarAttr(prog, "ax", pg.xBuf, 0, 0);
      this._bindScalarAttr(prog, "ay", pg.yBuf, 0, 0);
      if (pg.sizeMode === 1 && pg.sBuf) this._bindScalarAttr(prog, "a_sval", pg.sBuf, 0, 0);
      else {
        this._disableAttr(prog, "a_sval");
        const loc = gl.getAttribLocation(prog, "a_sval");
        if (loc >= 0) gl.vertexAttrib1f(loc, 0.5);
      }
      gl.drawArrays(gl.POINTS, 0, pg.n);
      slot++;
    }
    gl.enable(gl.BLEND);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this._pickDirty = false;
  }

  _pickAt(cssX, cssY) {
    if (!this._pickable) return null;
    if (this._pickDirty) this._renderPick();
    const gl = this.gl;
    const px = Math.round(cssX * this.dpr);
    const py = Math.round((this.plot.h - cssY) * this.dpr); // GL origin bottom-left
    if (px < 0 || py < 0 || px >= this.canvas.width || py >= this.canvas.height) return null;
    const buf = new Uint8Array(4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.pickFbo);
    gl.readPixels(px, py, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, buf);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    if (buf[3] === 0) return null;
    const slot = buf[3] - 1;
    const index = buf[0] | (buf[1] << 8) | (buf[2] << 16);
    const g = this.gpuTraces.find((t) => t.pickSlot === slot && markOf(t.trace.kind).pointPick);
    if (!g) return null;
    return { trace: g.trace.id, index, g };
  }

  _decodeValue(values, meta, index) {
    if (!values || !meta || index < 0 || index >= values.length) return NaN;
    return values[index] / (meta.scale || 1) + meta.offset;
  }

  _dataFromCanvas(cssX, cssY, xAxisId = "x", yAxisId = "y") {
    const [x0, x1] = this._axisRange(xAxisId);
    const [y0, y1] = this._axisRange(yAxisId);
    const xAxis = this._axis(xAxisId);
    const yAxis = this._axis(yAxisId);
    const cx0 = this._axisCoord(xAxis, x0);
    const cx1 = this._axisCoord(xAxis, x1);
    const cy0 = this._axisCoord(yAxis, y0);
    const cy1 = this._axisCoord(yAxis, y1);
    if (![cx0, cx1, cy0, cy1].every(Number.isFinite)) return [NaN, NaN];
    return [
      this._axisValue(xAxis, cx0 + (cssX / this.plot.w) * (cx1 - cx0)),
      this._axisValue(yAxis, cy1 - (cssY / this.plot.h) * (cy1 - cy0)),
    ];
  }

  _nearestCpuIndex(g, dataX) {
    const cpu = g && g._cpu;
    if (!cpu || !cpu.x || !cpu.x.length) return -1;
    const xMeta = cpu.xMeta || g.xMeta;
    const axis = this._axis(g.xAxis);
    const target = this._axisCoord(axis, dataX);
    let best = -1;
    let bestDist = Infinity;
    const limit = Math.min(cpu.x.length, g.n || cpu.x.length);
    for (let i = 0; i < limit; i++) {
      const x = this._decodeValue(cpu.x, xMeta, i);
      const d = Math.abs(this._axisCoord(axis, x) - target);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    }
    return best;
  }

  _hoverAt(cssX, cssY) {
    const maxPx = 12;
    let best = null;
    for (const g of this.gpuTraces) {
      if (g.tier === "density") continue;
      const [dataX, dataY] = this._dataFromCanvas(cssX, cssY, g.xAxis, g.yAxis);
      if (!Number.isFinite(dataX) || !Number.isFinite(dataY)) continue;
      if (g.heatmap && g._cpuHeatmap) {
        const hit = this._heatmapHover(g, dataX, dataY);
        if (hit) return hit;
        continue;
      }
      if (g.trace.bar && g._cpu) {
        const hit = this._barHover(g, dataX, dataY);
        if (hit) return hit;
        continue;
      }
      if (g._cpuRect) {
        const hit = this._rectHover(g, dataX, dataY);
        if (hit) return hit;
        continue;
      }
      if (!g._cpu || !g._cpu.x || !g._cpu.y) continue;
      const idx = this._nearestCpuIndex(g, dataX);
      if (idx < 0) continue;
      const x = this._decodeValue(g._cpu.x, g._cpu.xMeta, idx);
      const y = this._decodeValue(g._cpu.y, g._cpu.yMeta, idx);
      const px = this._dataPx(g.xAxis, x) - this.plot.x;
      const py = this._dataPx(g.yAxis, y) - this.plot.y;
      const dist = Math.hypot(px - cssX, py - cssY);
      if (dist <= maxPx && (!best || dist < best.dist)) {
        best = { trace: g.trace.id, index: idx, g, dist, synthetic: true };
      }
    }
    return best;
  }

  _barHover(g, dataX, dataY) {
    const cpu = g._cpu;
    const horizontal = g.orientation === 1;
    const limit = Math.min(cpu.x.length, cpu.y.length, g.n || cpu.x.length);
    for (let i = 0; i < limit; i++) {
      const x = this._decodeValue(cpu.x, cpu.xMeta, i);
      const y = this._decodeValue(cpu.y, cpu.yMeta, i);
      const value0 = g.value0Mode === 1 && cpu.value0
        ? this._decodeValue(cpu.value0, horizontal ? g.value0Meta : g.value0Meta, i)
        : g.value0Const;
      const lo = Math.min(value0 ?? 0, horizontal ? x : y);
      const hi = Math.max(value0 ?? 0, horizontal ? x : y);
      if (horizontal) {
        if (dataX >= lo && dataX <= hi && Math.abs(dataY - y) <= g.width / 2) {
          return { trace: g.trace.id, index: i, g, synthetic: true };
        }
      } else if (Math.abs(dataX - x) <= g.width / 2 && dataY >= lo && dataY <= hi) {
        return { trace: g.trace.id, index: i, g, synthetic: true };
      }
    }
    return null;
  }

  _rectHover(g, dataX, dataY) {
    const r = g._cpuRect;
    const limit = Math.min(r.x0.length, r.x1.length, r.y0.length, r.y1.length, g.n || r.x0.length);
    for (let i = 0; i < limit; i++) {
      const x0 = this._decodeValue(r.x0, r.x0Meta, i);
      const x1 = this._decodeValue(r.x1, r.x1Meta, i);
      const y0 = this._decodeValue(r.y0, r.y0Meta, i);
      const y1 = this._decodeValue(r.y1, r.y1Meta, i);
      if (
        dataX >= Math.min(x0, x1) && dataX <= Math.max(x0, x1) &&
        dataY >= Math.min(y0, y1) && dataY <= Math.max(y0, y1)
      ) {
        return { trace: g.trace.id, index: i, g, synthetic: true };
      }
    }
    return null;
  }

  _heatmapHover(g, dataX, dataY) {
    const h = g.heatmap;
    if (!h || !g._cpuHeatmap) return null;
    const [x0, x1] = h.xRange;
    const [y0, y1] = h.yRange;
    if (dataX < x0 || dataX > x1 || dataY < y0 || dataY > y1) return null;
    const col = Math.min(h.w - 1, Math.max(0, Math.floor(((dataX - x0) / (x1 - x0)) * h.w)));
    const row = Math.min(h.h - 1, Math.max(0, Math.floor(((dataY - y0) / (y1 - y0)) * h.h)));
    return { trace: g.trace.id, index: row * h.w + col, g, heatmap: { row, col }, synthetic: true };
  }

  _showTooltip(hit, clientX, clientY) {
    const row = this._localRow(hit);
    this._lastRow = row;
    this._renderTooltip(row, clientX, clientY);
    if (this._interactionFlag("hover")) {
      this._dispatchChartEvent("hover", {
        row,
        trace: hit.trace,
        index: hit.index,
        view: this._eventView("hover"),
      });
    }
    if (this.comm) {
      // Exact f64 values from the kernel canonical store (§16). The local row
      // (decoded from f32) shows instantly; the exact one replaces it.
      // NOTE: picks use their own sequence — sharing this.seq with view
      // requests made a hover invalidate an in-flight tier_update, freezing
      // the stale tier (found in staff review).
      this._pickSeq = (this._pickSeq || 0) + 1;
      const req = { type: "pick", seq: this._pickSeq, trace: hit.trace, index: hit.index };
      // Drilled picks name the subset version they hit against; the kernel
      // returns None instead of translating through the wrong subset (§16/§17).
      const hg = hit.g;
      if (hg && hg.tier === "density" && hg.drill && hg.drill.seq !== undefined) {
        req.drill_seq = hg.drill.seq;
      }
      this.comm.send(req);
    }
  }

  _localRow(hit) {
    // Approximate readout from the resident f32 (used in standalone export and
    // as the instant value before the kernel's exact reply, §37). Only present
    // when CPU copies were retained (renderStandalone); the widget path replaces
    // this with the kernel's exact f64 row (§16).
    const g = hit.g;
    const cpu = g._cpu;
    const row = { trace: g.trace.id, index: hit.index };
    if (hit.heatmap && g.heatmap && g._cpuHeatmap) {
      const h = g.heatmap;
      const { row: heatRow, col } = hit.heatmap;
      const rawX = h.xRange[0] + (col + 0.5) * ((h.xRange[1] - h.xRange[0]) / h.w);
      const rawY = h.yRange[0] + (heatRow + 0.5) * ((h.yRange[1] - h.yRange[0]) / h.h);
      const [x, xKind] = this._sourceDisplayValue(g, "x", rawX, "float");
      const [y, yKind] = this._sourceDisplayValue(g, "y", rawY, "float");
      row.x = x;
      row.y = y;
      if (xKind !== undefined) row.x_kind = xKind;
      if (yKind !== undefined) row.y_kind = yKind;
      const norm = g._cpuHeatmap.grid[hit.index];
      row.color_value = this._denormalizeUnit(norm, g.trace.color && g.trace.color.domain);
    } else if (g._cpuRect) {
      const r = g._cpuRect;
      const x0 = this._decodeValue(r.x0, r.x0Meta, hit.index);
      const x1 = this._decodeValue(r.x1, r.x1Meta, hit.index);
      const y0 = this._decodeValue(r.y0, r.y0Meta, hit.index);
      const y1 = this._decodeValue(r.y1, r.y1Meta, hit.index);
      row.x = x0 + (x1 - x0) / 2;
      row.y = y1;
      row.x_kind = r.x0Meta.kind;
      row.y_kind = r.y1Meta.kind;
    } else if (cpu) {
      const xMeta = cpu.xMeta || g.xMeta;
      const yMeta = cpu.yMeta || g.yMeta;
      row.x = this._decodeValue(cpu.x, xMeta, hit.index);
      row.y = this._decodeValue(cpu.y, yMeta, hit.index);
      row.x_kind = xMeta && xMeta.kind;
      row.y_kind = yMeta && yMeta.kind;
      const color = g.trace.color;
      if (cpu.color && color) {
        if (color.mode === "categorical" && Array.isArray(color.categories)) {
          const code = Math.round(cpu.color[hit.index]);
          if (code >= 0 && code < color.categories.length) {
            row.color_category = String(color.categories[code]);
          }
        } else if (color.mode === "continuous") {
          row.color_value = this._denormalizeUnit(cpu.color[hit.index], color.domain);
        }
      }
      const size = g.trace.size;
      if (cpu.size && size && size.mode === "continuous") {
        row.size_value = this._denormalizeUnit(cpu.size[hit.index], size.domain);
      }
    }
    this._applySharedTooltipFields(row);
    return row;
  }

  _sourceDisplayValue(g, channel, value, kind) {
    const axis = channel === "x" ? this._axis(g && g.xAxis) : this._axis(g && g.yAxis);
    if (channel === "x" && axis.kind === "category") {
      return [fmtCategory(value, axis.categories || []), undefined];
    }
    if (channel === "y" && axis.kind === "category") {
      return [fmtCategory(value, axis.categories || []), undefined];
    }
    return [value, kind];
  }

  _sourceValue(g, source, index) {
    if (!g || index < 0) return [undefined, undefined];
    const channel = source.channel;
    if (channel === "x" || channel === "y") {
      const cpu = g._cpu;
      if (!cpu || !cpu[channel]) return [undefined, undefined];
      const meta = channel === "x" ? (cpu.xMeta || g.xMeta) : (cpu.yMeta || g.yMeta);
      const value = this._decodeValue(cpu[channel], meta, index);
      if (!Number.isFinite(value)) return [undefined, undefined];
      return this._sourceDisplayValue(g, channel, value, meta && meta.kind);
    }
    if (channel === "color_value") {
      if (g._cpuHeatmap && g._cpuHeatmap.grid && g.trace.color) {
        return [this._denormalizeUnit(g._cpuHeatmap.grid[index], g.trace.color.domain), undefined];
      }
      if (g._cpu && g._cpu.color && g.trace.color) {
        return [this._denormalizeUnit(g._cpu.color[index], g.trace.color.domain), undefined];
      }
    }
    if (channel === "color_category" && g._cpu && g._cpu.color && g.trace.color) {
      const code = Math.round(g._cpu.color[index]);
      const categories = g.trace.color.categories || [];
      if (code >= 0 && code < categories.length) return [String(categories[code]), undefined];
    }
    if (channel === "size_value" && g._cpu && g._cpu.size && g.trace.size) {
      return [this._denormalizeUnit(g._cpu.size[index], g.trace.size.domain), undefined];
    }
    return [undefined, undefined];
  }

  _applySharedTooltipFields(row) {
    const sources = this.spec.tooltip && this.spec.tooltip.sources;
    if (!sources || typeof sources !== "object" || row.x === undefined) return;
    for (const [field, entries] of Object.entries(sources)) {
      if (!Array.isArray(entries) || row[field] !== undefined) continue;
      const source = entries.find((entry) => entry.trace === row.trace) || entries[0];
      if (!source || !Number.isFinite(Number(source.trace))) continue;
      const g = this.gpuTraces.find((trace) => trace.trace.id === source.trace);
      if (!g) continue;
      let idx = Number.isInteger(row.index) && source.trace === row.trace ? row.index : -1;
      if (
        !g._cpuHeatmap &&
        (idx < 0 || !g._cpu || !g._cpu.x || idx >= g._cpu.x.length)
      ) {
        idx = this._nearestCpuIndex(g, row.x);
      }
      const [value, kind] = this._sourceValue(g, source, idx);
      if (value === undefined) continue;
      row[field] = value;
      if (kind !== undefined) row[`${field}_kind`] = kind;
    }
  }

  _denormalizeUnit(value, domain) {
    const v = Number(value);
    if (!Number.isFinite(v)) return v;
    if (!Array.isArray(domain) || domain.length < 2) return v;
    const lo = Number(domain[0]);
    const hi = Number(domain[1]);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return v;
    return lo + v * (hi - lo);
  }

  _defaultTooltipLines(row) {
    const lines = [];
    if (row.x !== undefined) lines.push(`x: ${fmtValue(row.x, row.x_kind)}`);
    if (row.y !== undefined) lines.push(`y: ${fmtValue(row.y, row.y_kind)}`);
    if (row.color_value !== undefined) lines.push(`color: ${fmtValue(row.color_value)}`);
    if (row.color_category !== undefined) lines.push(`${row.color_category}`);
    if (row.size_value !== undefined) lines.push(`size: ${fmtValue(row.size_value)}`);
    if (!lines.length) lines.push(`#${row.index}`);
    return lines;
  }

  _tooltipLookup(row, field) {
    const aliases = (this.spec.tooltip && this.spec.tooltip.aliases) || {};
    const key = row[field] !== undefined ? field : aliases[field];
    if (!key || row[key] === undefined) return [undefined, undefined];
    return [row[key], row[`${key}_kind`]];
  }

  _formatTooltipValue(value, kind, format) {
    const formatted = fmtNumberSpec(value, format);
    if (formatted !== null) return formatted;
    return fmtValue(value, kind);
  }

  _tooltipLines(row) {
    const tooltip = this.spec.tooltip || {};
    if (!tooltip.title && !Array.isArray(tooltip.fields)) return this._defaultTooltipLines(row);
    const formats = tooltip.format || {};
    const lines = [];
    if (typeof tooltip.title === "string") {
      const title = tooltip.title.replace(/\{([^}]+)\}/g, (_, field) => {
        const [value, kind] = this._tooltipLookup(row, field);
        return value === undefined ? "" : this._formatTooltipValue(value, kind, formats[field]);
      });
      if (title) lines.push(title);
    }
    if (Array.isArray(tooltip.fields)) {
      for (const field of tooltip.fields) {
        if (typeof field !== "string") continue;
        const [value, kind] = this._tooltipLookup(row, field);
        if (value === undefined) continue;
        lines.push(`${field}: ${this._formatTooltipValue(value, kind, formats[field])}`);
      }
    }
    return lines.length ? lines : this._defaultTooltipLines(row);
  }

  _renderTooltip(row, clientX, clientY) {
    if (!row || this.spec.show_tooltip === false) {
      this.tooltip.style.display = "none";
      return;
    }
    const rect = this.root.getBoundingClientRect();
    const lx = clientX - rect.left;
    const ly = clientY - rect.top;
    const lines = this._tooltipLines(row);
    // Text nodes, not innerHTML: category labels are user data and must never
    // be parsed as markup (a category named "<img onerror=…>" is just a label).
    this.tooltip.textContent = "";
    lines.forEach((ln, i) => {
      if (i) this.tooltip.appendChild(document.createElement("br"));
      this.tooltip.appendChild(document.createTextNode(ln));
    });
    this.tooltip.style.display = "block";
    const tw = this.tooltip.offsetWidth;
    this.tooltip.style.left = Math.min(lx + 12, this.size.w - tw - 4) + "px";
    this.tooltip.style.top = ly + 12 + "px";
  }

  // -- interaction ----------------------------------------------------------

  _initInteraction() {
    const c = this.canvas;
    let drag = null;
    let band = null;

    // Rubber-band overlay for box-select (§34) — DOM, above the canvas.
    this.selRect = document.createElement("div");
    this.selRect.style.cssText =
      "position:absolute;display:none;pointer-events:none;z-index:4;" +
      "border:1px solid var(--chart-selection, rgba(90,140,240,.9));" +
      "background:var(--chart-selection-fill, rgba(90,140,240,.15));";
    this._applySlot(this.selRect, "selection");
    this.root.appendChild(this.selRect);

    if (this._interactionFlag("crosshair")) {
      this.crosshairX = document.createElement("div");
      this.crosshairX.style.cssText =
        "position:absolute;display:none;pointer-events:none;z-index:3;" +
        "width:1px;background:var(--chart-crosshair, rgba(15,23,42,.42));";
      this._applySlot(this.crosshairX, "crosshair_x");
      this.root.appendChild(this.crosshairX);
      this.crosshairY = document.createElement("div");
      this.crosshairY.style.cssText =
        "position:absolute;display:none;pointer-events:none;z-index:3;" +
        "height:1px;background:var(--chart-crosshair, rgba(15,23,42,.42));";
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
      this._dispatchChartEvent("leave", { view: this._eventView("leave") });
      if (hadHover) this.draw();
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
  }

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
  }

  _hideCrosshair() {
    if (this.crosshairX) this.crosshairX.style.display = "none";
    if (this.crosshairY) this.crosshairY.style.display = "none";
  }

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
  }

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
    if (band.mode === "zoom") {
      this.selRect.style.border = "1px solid var(--chart-zoom-selection, rgba(120,120,120,.9))";
      this.selRect.style.background = "var(--chart-zoom-selection-fill, rgba(120,120,120,.12))";
    } else {
      this.selRect.style.border = "1px solid var(--chart-selection, rgba(90,140,240,.9))";
      this.selRect.style.background = "var(--chart-selection-fill, rgba(90,140,240,.15))";
    }
    this.selRect.style.display = "block";
    this.selRect.style.left = cx + "px";
    this.selRect.style.top = cy + "px";
    this.selRect.style.width = Math.max(0, x2 - cx) + "px";
    this.selRect.style.height = Math.max(0, y2 - cy) + "px";
    void rect;
  }

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
  }

  // Standalone selection (no kernel): mask the retained CPU f32 columns (§37).
  _selectLocal(x0, x1, y0, y1) {
    let total = 0;
    for (const g of this.gpuTraces) {
      // _cpu only exists where the standalone entry retained copies (retainCpu).
      if (!g._cpu || g.tier === "density") continue;
      const cx = g._cpu.x, cy = g._cpu.y;
      const ox = g.xMeta.offset, sx = g.xMeta.scale || 1;
      const oy = g.yMeta.offset, sy = g.yMeta.scale || 1;
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
  }

  _applySelMask(g, maskF32) {
    const gl = this.gl;
    if (!g.selBuf) g.selBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, g.selBuf);
    gl.bufferData(gl.ARRAY_BUFFER, maskF32, gl.STATIC_DRAW);
    g.selActive = true;
  }

  _clearSelection() {
    for (const g of this.gpuTraces) {
      g.selActive = false;
      if (g.drill) g.drill.selActive = false;
    }
    this._selectionCount = 0;
    if (this.comm) this.comm.send({ type: "select_clear" });
    this._dispatchChartEvent("select", { total: 0, view: this._eventView("select_clear") });
  }

  // -- modebar & zoom (Plotly-parity controls) ------------------------------

  _buildModebar(root) {
    if (this.spec.show_modebar === false) return;
    const bar = document.createElement("div");
    // Visible by default, then stronger on hover. At .25 opacity the controls
    // were technically present but easy to miss in embedded dashboards.
    bar.style.cssText =
      `position:absolute;top:${this.plot.y + 4}px;left:${this.plot.x + 4}px;z-index:6;` +
      "display:flex;gap:1px;opacity:.72;transition:opacity .15s;" +
      "background:var(--chart-modebar-bg, rgba(255,255,255,.78));" +
      "border:1px solid rgba(128,128,128,.18);" +
      "border-radius:4px;padding:1px;box-shadow:0 1px 4px rgba(0,0,0,.08);";
    this._applySlot(bar, "modebar");
    this._listen(root, "pointerenter", () => { bar.style.opacity = "1"; });
    this._listen(root, "pointerleave", () => { bar.style.opacity = ".72"; });
    this._modebar = bar;
    this._modeBtns = {};

    const col = cssColor(this.theme.axis);
    const mk = (name, title, onClick, toggles) => {
      const b = document.createElement("button");
      b.type = "button";
      b.title = title;
      b.innerHTML = this._icon(name);
      b.style.cssText =
        "display:flex;align-items:center;justify-content:center;width:26px;height:24px;" +
        "padding:0;border:none;background:transparent;cursor:pointer;border-radius:3px;" +
        `color:${col};pointer-events:auto;`;
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
    this._setDragMode(this.dragMode);
  }

  _setDragMode(mode) {
    this.dragMode = mode;
    // Cursor telegraphs the gesture: grab for pan, crosshair for box-zoom.
    if (this.canvas) this.canvas.style.cursor = mode === "zoom" ? "crosshair" : "grab";
    for (const [name, btn] of Object.entries(this._modeBtns || {})) {
      btn.style.background = name === mode ? "rgba(128,128,128,.22)" : "transparent";
    }
  }

  _prefersReducedMotion() {
    return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
  }

  _cancelViewAnimation() {
    if (this._animRaf) cancelAnimationFrame(this._animRaf);
    this._animRaf = null;
    this._viewAnim = null;
  }

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
    const now = performance.now();
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
  }

  // Center-anchored zoom (f<1 in, f>1 out) — the modebar buttons; wheel is
  // cursor-anchored. Shares the §16 precision floor so we never zoom past f32.
  _zoomBy(f, animate = false) {
    const base = this._viewAnim ? this._viewAnim.target : this.view;
    const { x0, x1, y0, y1 } = base;
    const xr = this._zoomAxisRange("x", x0, x1, f, 0.5);
    const yr = this._zoomAxisRange("y", y0, y1, f, 0.5);
    if (!xr || !yr) return;
    this._setView({ x0: xr[0], x1: xr[1], y0: yr[0], y1: yr[1] }, { animate });
  }

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
  }

  _zoomAt(f, fx, fy, animate = false, duration = 120) {
    const base = this._viewAnim ? this._viewAnim.target : this.view;
    const { x0, x1, y0, y1 } = base;
    const xr = this._zoomAxisRange("x", x0, x1, f, fx);
    const yr = this._zoomAxisRange("y", y0, y1, f, fy);
    if (!xr || !yr) return;
    this._setView({ x0: xr[0], x1: xr[1], y0: yr[0], y1: yr[1] }, { animate, duration });
  }

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
  }

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
  }

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
      default:
        return svg("");
    }
  }

  _hover(e) {
    if (this._transitionActive()) {
      const hadHover = this._hoverId !== -1;
      this._hoverId = -1;
      this._hoverTarget = null;
      this.tooltip.style.display = "none";
      if (hadHover) this.draw();
      return;
    }
    const rect = this.canvas.getBoundingClientRect();
    const cssX = e.clientX - rect.left;
    const cssY = e.clientY - rect.top;
    const hit = this._pickAt(cssX, cssY) || this._hoverAt(cssX, cssY);
    if (!hit) {
      const hadHover = this._hoverId !== -1;
      this._hoverId = -1;
      this._hoverTarget = null;
      this.tooltip.style.display = "none";
      if (hadHover) this.draw();
      return;
    }
    const id = hit.trace * 1e9 + hit.index;
    this._lastHoverXY = { clientX: e.clientX, clientY: e.clientY };
    if (id === this._hoverId) {
      this._renderTooltip(this._lastRow, e.clientX, e.clientY);
      return;
    }
    this._hoverId = id;
    this._hoverTarget = hit;
    this._showTooltip(hit, e.clientX, e.clientY);
    this.draw();
  }

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
  }

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
  }

  _onKernelMsg(msg, buffers) {
    if (this._destroyed) return;
    if (!msg) return;
    if (msg.type === "tier_update") {
      if (msg.seq !== this.seq) return;
      for (const upd of msg.traces) {
        const g = this.gpuTraces.find((t) => t.trace.id === upd.id);
        if (!g) continue;
        const gl = this.gl;
        gl.bindBuffer(gl.ARRAY_BUFFER, g.xBuf);
        gl.bufferData(gl.ARRAY_BUFFER, this._asF32(buffers[upd.x.buf]), gl.STATIC_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, g.yBuf);
        gl.bufferData(gl.ARRAY_BUFFER, this._asF32(buffers[upd.y.buf]), gl.STATIC_DRAW);
        g.xMeta = { ...g.xMeta, offset: upd.x.offset, scale: upd.x.scale };
        g.yMeta = { ...g.yMeta, offset: upd.y.offset, scale: upd.y.scale };
        g.n = Math.min(upd.x.len, upd.y.len);
        if (upd.base && g.baseBuf) {
          gl.bindBuffer(gl.ARRAY_BUFFER, g.baseBuf);
          gl.bufferData(gl.ARRAY_BUFFER, this._asF32(buffers[upd.base.buf]), gl.STATIC_DRAW);
          g.baseMeta = { ...g.baseMeta, offset: upd.base.offset, scale: upd.base.scale };
          g.n = Math.min(g.n, upd.base.len);
        }
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
      this._dispatchChartEvent("select", {
        total: this._selectionCount,
        view: this._eventView("select"),
      });
    }
  }

  // -- Tier-2 drill-in (§5: tier follows the *visible* count) ---------------

  // Drill lifecycle, exit fades, and the density-source cache live in
  // 45_lod.js (chart-agnostic). These delegates keep the ChartView API
  // stable for tests and callers.
  _applyDrill(g, upd, buffers) {
    lodApplyDrill(this, g, upd, buffers);
  }

  _dropDrill(g) {
    lodDropDrill(this, g);
  }

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
  }

  _viewInsideRange(xRange, yRange) {
    if (!xRange || !yRange) return false;
    return this._viewInside({ x0: xRange[0], x1: xRange[1], y0: yRange[0], y1: yRange[1] });
  }

  _asF32(b) {
    if (b instanceof ArrayBuffer) return new Float32Array(b);
    if (b.byteOffset % 4 === 0) {
      return new Float32Array(b.buffer, b.byteOffset, Math.floor(b.byteLength / 4));
    }
    return new Float32Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
  }

  _asU32(b) {
    if (b instanceof ArrayBuffer) return new Uint32Array(b);
    if (b.byteOffset % 4 === 0) {
      return new Uint32Array(b.buffer, b.byteOffset, Math.floor(b.byteLength / 4));
    }
    return new Uint32Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
  }

  refreshTheme() {
    if (this._destroyed) return;
    this.theme = readTheme(this.root);
    for (const g of this.gpuTraces) {
      // Re-resolve CSS-expressed constant colors (§36 live re-resolution);
      // each mark kind knows where its constant color lives in the spec.
      markOf(g.trace.kind).refreshColor?.(this, g);
    }
    this.draw();
  }

  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    this._ro?.disconnect();
    this._io?.disconnect();
    this._io = null;
    this._themeWatch?.removeEventListener?.("change", this._onScheme);
    this._dprMq?.removeEventListener?.("change", this._onDprChange);
    this._dprMq = null;
    this._unsubscribeComm?.();
    this._unsubscribeComm = null;
    for (const { target, type, handler, options } of this._listeners.splice(0)) {
      target.removeEventListener(type, handler, options);
    }
    clearTimeout(this._viewTimer);
    this._viewTimer = null;
    if (this._viewEventRaf) cancelAnimationFrame(this._viewEventRaf);
    this._viewEventRaf = null;
    if (this._wheelZoomRaf) cancelAnimationFrame(this._wheelZoomRaf);
    this._wheelZoomRaf = null;
    this._pendingWheelZoom = null;
    this._linkChannel?.close?.();
    this._linkChannel = null;
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
    this._cancelViewAnimation();
    this._destroyGlResources();
    this.gl = null;
    this.root.remove();
  }

  _deleteBuffers(obj, names) {
    const gl = this.gl;
    if (!gl || !obj) return;
    const seen = new Set();
    for (const name of names) {
      const buf = obj[name];
      if (buf && !seen.has(buf)) {
        seen.add(buf);
        gl.deleteBuffer(buf);
      }
      obj[name] = null;
    }
  }

  _destroyTraceResources(g, texSeen) {
    if (!g) return;
    this._deleteBuffers(g, [
      "xBuf", "yBuf", "cBuf", "sBuf", "selBuf", "baseBuf",
      "x0Buf", "x1Buf", "y0Buf", "y1Buf",
      "posBuf", "value1Buf", "value0Buf",
    ]);
    this._deleteBuffers(g.drill, ["xBuf", "yBuf", "cBuf", "sBuf", "selBuf", "dBuf"]);
    const textures = [];
    if (g.heatmap) textures.push(g.heatmap.tex);
    for (const d of g.densityCache || []) textures.push(d && d.tex);
    if (g.density) textures.push(g.density.tex);
    if (g._shownDensity) textures.push(g._shownDensity.tex);
    for (const tex of textures) {
      if (tex && !texSeen.has(tex)) {
        texSeen.add(tex);
        this.gl.deleteTexture(tex);
      }
    }
    g.drill = null;
    g.density = null;
    g._shownDensity = null;
    g.densityCache = [];
    g.heatmap = null;
    g._cpu = null;
  }

  _destroyGlResources() {
    const gl = this.gl;
    if (!gl) return;
    const texSeen = new Set();
    for (const g of this.gpuTraces || []) this._destroyTraceResources(g, texSeen);
    for (const tex of this._lutCache.values()) {
      if (tex && !texSeen.has(tex)) {
        texSeen.add(tex);
        gl.deleteTexture(tex);
      }
    }
    this._lutCache.clear();
    if (this.pickFbo) gl.deleteFramebuffer(this.pickFbo);
    if (this.pickTex && !texSeen.has(this.pickTex)) gl.deleteTexture(this.pickTex);
    this.pickFbo = null;
    this.pickTex = null;
    if (this.quad) gl.deleteBuffer(this.quad);
    this.quad = null;
    for (const p of this._glPrograms || []) if (p) gl.deleteProgram(p);
    this._glPrograms = [];
    this.gpuTraces = [];
  }
}
