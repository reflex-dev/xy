// ---------------------------------------------------------------------------
// ChartView
// ---------------------------------------------------------------------------

const MARGIN = { l: 62, r: 14, t: 10, b: 42 };
const COLORBAR_THICKNESS = 18;
const COLORBAR_GAP = 24;
let XY_A11Y_ID = 0;
const XY_SR_ONLY_STYLE =
  "position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;" +
  "clip:rect(0,0,0,0);white-space:nowrap;border:0;";
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

// Dashboard context governor (production-readiness: the WebGL-context cap).
// Browsers cap live WebGL contexts per page (~16 in Chrome) and LRU-evict the
// oldest on overflow, permanently blanking the earliest charts of a big
// dashboard. The governor keeps this library inside a budget instead: when a
// view is about to acquire a context and the page is at budget, the
// least-recently-visible *off-screen* view releases its own context via
// WEBGL_lose_context — a controlled loss the existing restore machinery can
// undo — and re-acquires when scrolled back into view. Under the budget no
// view ever releases, so pages with few charts behave exactly as before.
// Every decision is observable (§28): `data-xy-ctx` on the canvas reads
// "live" | "released" | "lost", and views count releases/recoveries.
const XY_CONTEXT_GOVERNOR = {
  views: new Set(),
  seq: 1,
  budget() {
    const v = typeof window !== "undefined" ? window.XY_CONTEXT_BUDGET : null;
    // 12 leaves headroom under Chrome's ~16 so host-page GL (maps, editors)
    // does not push chart contexts into browser-side eviction.
    return Number.isFinite(v) && v >= 1 ? Math.floor(v) : 12;
  },
  register(view) {
    this.views.add(view);
  },
  unregister(view) {
    view._ctxPendingReservation = false;
    this.views.delete(view);
  },
  // Called before a view acquires (or re-acquires) a GL context. Releases
  // least-recently-visible off-screen views until the requester fits the
  // budget. If every live view is visible, overflow is allowed — the browser
  // may LRU-evict, and eviction recovery rebuilds on re-entry.
  reserve(requester) {
    const live = [];
    let pending = 0;
    for (const view of this.views) {
      if (view !== requester && view.gl && !view._glLost && !view._destroyed) live.push(view);
      if (view !== requester && view._ctxPendingReservation && !view._destroyed) pending += 1;
    }
    const needsReservation = !requester._ctxPendingReservation;
    requester._ctxPendingReservation = true;
    let over = live.length + pending + (needsReservation ? 1 : 0) - this.budget();
    if (over <= 0) return;
    const candidates = live
      .filter((view) => !view._ctxVisible)
      .sort((a, b) => (a._ctxSeenSeq || 0) - (b._ctxSeenSeq || 0));
    for (const view of candidates) {
      if (over <= 0) break;
      if (view._releaseContext()) over -= 1;
    }
    if (over <= 0) return;
    // Every remaining live view is on screen (a dense subplot grid). Release
    // least-recently-visible ones anyway: the snapshot stand-in keeps them
    // looking rendered, and pointer entry revives them. Letting the browser
    // LRU-evict instead blanks visible charts with no recovery until the
    // page scrolls (§28: data-xy-ctx stays legible either way).
    const visible = live
      .filter((view) => view._ctxVisible)
      .sort((a, b) => (a._ctxSeenSeq || 0) - (b._ctxSeenSeq || 0));
    for (const view of visible) {
      if (over <= 0) break;
      if (view._releaseContext()) over -= 1;
    }
  },
  acquired(requester) {
    requester._ctxPendingReservation = false;
  },
  cancel(requester) {
    requester._ctxPendingReservation = false;
  },
};

// Initial visibility estimate for the governor: IntersectionObserver entries
// arrive asynchronously, but big dashboards create every chart synchronously —
// the estimate lets reserve() prefer below-the-fold charts immediately. The
// 25% margin matches the observer's rootMargin (recovery hysteresis).
function xyInitiallyVisible(el) {
  if (typeof window === "undefined" || !el.getBoundingClientRect) return true;
  const rect = el.getBoundingClientRect();
  if (!rect.width && !rect.height) return false; // hidden boot slot: recoverable
  const vh = window.innerHeight || 0;
  const vw = window.innerWidth || 0;
  return (
    rect.bottom > -0.25 * vh && rect.top < 1.25 * vh && rect.right > -0.25 * vw && rect.left < 1.25 * vw
  );
}

class ChartView {
  constructor(el, spec, buffer, comm) {
    if (spec.protocol !== PROTOCOL) {
      el.textContent =
        `xy: protocol mismatch (client speaks ${PROTOCOL}, kernel sent ${spec.protocol}). ` +
        "Update the xy package and restart the kernel.";
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
    this._progCache = new Map();
    this._bufSeq = 0;
    this._destroyed = false;
    this._hoverId = -1;
    this._hoverTarget = null;
    this._viewEventRaf = null;
    this._linkedSource = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    // pan | zoom | internal selection modes (the modebar exposes only pan/zoom)
    this.dragMode = "pan";

    // Responsive size: "100%" means the *container* owns that axis — measure
    // it now, track it with a ResizeObserver below. Numeric sizes are fixed.
    // (height:"100%" needs a parent with a defined height, per usual CSS.)
    this.fluid = spec.width === "100%";
    this.fluidH = spec.height === "100%";
    const rect = this.fluid || this.fluidH ? el.getBoundingClientRect() : null;
    const cw = this.fluid ? Math.round(rect.width) || 640 : spec.width; // 0 = hidden; RO corrects
    const ch = this.fluidH ? Math.round(rect.height) || 420 : spec.height;
    // Fluid floors stay high (a collapsed/hidden container must not produce a
    // degenerate chart), but explicit sizes are honored down to a tiny floor:
    // dense pyplot subplot grids legitimately build sub-120px panels whose
    // plot boxes must land exactly on their matplotlib rects.
    this.size = {
      w: Math.max(this.fluid ? 120 : 48, cw),
      h: Math.max(this.fluidH ? 120 : 48, ch),
    };
    this._layout();

    this._buildDom(el);
    // getComputedStyle yields nothing on a detached element, so a chart
    // constructed before its output node lands in the document (notebook
    // webviews attach asynchronously) would freeze on fallback theme colors —
    // gray grid over a themed card. Track staleness and heal on the first
    // frame (or visibility change) after connection.
    this.theme = readTheme(this.root);
    this._themeStale = !this.root.isConnected;
    // Retained for GL context restore: the payload is screen-bounded (§29) so
    // keeping it is cheap, and every GPU object is rebuildable from
    // spec + payload by design (§18/§27).
    this._payload = buffer;
    this._glLost = false;
    this._ctxReleasedExt = null;
    this._ctxReleases = 0;
    this._ctxRecoveries = 0;
    this._ctxVisible = xyInitiallyVisible(el);
    XY_CONTEXT_GOVERNOR.register(this);
    if (this._ctxVisible) this._ctxSeenSeq = XY_CONTEXT_GOVERNOR.seq++;
    this._contextLossCount = 0;
    this._contextRestoreCount = 0;
    this._contextRecoveryError = null;
    this._initGl(buffer);
    this._initA11y();
    this.root.dataset.xyContextState = "ready";
    this._initContextLossRecovery();
    this._armContextVisibilityWatch();
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
    // Framework theme switches usually toggle a class (for example `.dark`)
    // on the chart or one of its ancestors without changing the OS color
    // scheme. Watch that cascade path as well so canvas/SVG paint refreshed
    // from --chart-* tokens stays in sync with the CSS-owned chart chrome.
    if (typeof MutationObserver !== "undefined") {
      this._themeMutationObserver = new MutationObserver(() => this.refreshTheme());
      for (let node = this.root; node; node = node.parentElement) {
        this._themeMutationObserver.observe(node, {
          attributes: true,
          attributeFilter: ["class", "style"],
        });
      }
    }

    this._unsubscribeComm = comm ? comm.onMessage((msg, buffers) => this._onKernelMsg(msg, buffers)) : null;
    this.draw();
  }

  _layout() {
    // Plot rect from the current size — margins fixed, data area flexes.
    const compact = this.size.w < 520;
    // Explicit padding (spec.padding = [top,right,bottom,left]) overrides the
    // label-aware defaults — zero padding gives an edge-to-edge sparkline.
    const pad = Array.isArray(this.spec.padding) ? this.spec.padding : null;
    const marginLeft = pad ? pad[3] : compact ? 46 : MARGIN.l;
    const colorbar = this.spec.colorbar;
    const verticalColorbar = colorbar && colorbar.orientation !== "horizontal";
    const horizontalColorbar = colorbar && colorbar.orientation === "horizontal";
    const colorbarRightRoom = verticalColorbar ? 86 + (colorbar.label ? 18 : 0) : 0;
    const colorbarBottomRoom = horizontalColorbar ? 38 + (colorbar.label ? 16 : 0) : 0;
    const marginRight = (pad ? pad[1] : compact ? 8 : MARGIN.r) + colorbarRightRoom;
    const marginTop = pad ? pad[0] : compact ? 6 : MARGIN.t;
    const marginBottom = (pad ? pad[2] : compact ? 36 : MARGIN.b) + colorbarBottomRoom;
    const hasBottomAxis = Object.values(this.axes || {}).some((axis) =>
      axis && String(axis.id || "").startsWith("x") && axis.side !== "top" &&
      this._axisTickLabelStrategy(axis) !== "none");
    this._bottomAxisRoom = hasBottomAxis ? (compact ? 36 : MARGIN.b) : 0;
    // A named x axis can own the top edge even when the primary x axis stays
    // on the bottom. Reserve one shared gutter for every top-side x axis;
    // multiple axes on the same side intentionally overlay until axis offsets
    // become part of the public API (the same rule used by secondary y axes).
    const topAxisRoom = Object.values(this.axes || {}).some((axis) =>
      axis && String(axis.id || "").startsWith("x") && axis.side === "top" &&
      this._axisTickLabelStrategy(axis) !== "none")
      ? (compact ? 26 : 32)
      : 0;
    const top = marginTop + (this.spec.title ? (compact ? 26 : 30) : 0) + topAxisRoom;
    const rightAxes = Object.values(this.axes || {}).filter((axis) =>
      axis && String(axis.id || "").startsWith("y") &&
      axis.side === "right" && this._axisTickLabelStrategy(axis) !== "none");
    // The vertical colorbar shifts right by this room (see _positionColorbar);
    // the Python SVG/raster exporters apply the identical 42/54 rule.
    this._rightAxisRoom = rightAxes.length ? (compact ? 42 : 54) : 0;
    const right = marginRight + this._rightAxisRoom;
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
    if (Array.isArray(axis.tick_values)) {
      const a = Math.min(lo, hi), b = Math.max(lo, hi);
      const ticks = axis.tick_values.map(Number).filter((v) => Number.isFinite(v) && v >= a && v <= b);
      return { ticks, labels: ticks, step: ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) : 1 };
    }
    if (axis.kind === "time") return timeTicks(lo, hi, target);
    if (axis.kind === "category") return categoryTicks(lo, hi, axis.categories || [], target);
    if (axis.scale === "log") return logTicks(lo, hi, target);
    return linearTicks(lo, hi, target);
  }

  _axisTickText(axis, value, step) {
    if (Array.isArray(axis.tick_values) && Array.isArray(axis.tick_labels)) {
      const index = axis.tick_values.findIndex((candidate) => Number(candidate) === Number(value));
      if (index >= 0 && index < axis.tick_labels.length) return String(axis.tick_labels[index]);
    }
    return fmtAxis(axis, value, step);
  }

  _axisTickTarget(axisId, fallback) {
    const axis = this._axis(axisId);
    const requested = Number(axis && axis.tick_count);
    if (Number.isFinite(requested) && requested > 0) {
      return Math.max(1, Math.min(200, requested));
    }
    return fallback;
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
    this.root.dispatchEvent(new CustomEvent(`xy:${name}`, {
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
    this._linkChannel = new BroadcastChannel(`xy:${group}`);
    this._linkChannel.onmessage = (event) => {
      const msg = event.data || {};
      if (msg.source === this._linkedSource) return;
      if (this._interactionFlag("link_select") && msg.selection) {
        const selection = msg.selection;
        if (selection.clear) this._clearSelection({ broadcast: false, dispatch: false });
        else if (selection.polygon) this._selectLocalPolygon(selection.polygon, { dispatch: false });
        else if (selection.range) {
          const { x0, x1, y0, y1 } = selection.range;
          if ([x0, x1, y0, y1].every(Number.isFinite)) {
            this._selectLocal(x0, x1, y0, y1, { dispatch: false });
          }
        }
        return;
      }
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

  _broadcastLinkedSelection(selection) {
    if (!this._linkChannel || !this._interactionFlag("link_select")) return;
    this._linkChannel.postMessage({ source: this._linkedSource, selection });
  }

  _applyClass(el, className) {
    if (typeof className !== "string") return;
    for (const token of className.split(/\s+/).filter(Boolean)) {
      try { el.classList.add(token); } catch (_) { /* Ignore invalid CSS class tokens. */ }
    }
  }

  _stylePropertyName(key) {
    if (key.startsWith("--")) return key;
    // Accept snake_case (the Python API form, e.g. `font_size`), camelCase
    // (React-style `fontSize`), and kebab-case interchangeably, normalizing all
    // to the CSS property name. The underscore pass is load-bearing: Python
    // kebab-normalizes keys only for its grammar check and ships the raw key in
    // the spec, so without it a validated `font_size` reached
    // setProperty("font_size", …) and the browser silently dropped it. It also
    // lets the unitless-property check below see the real (kebab) name.
    return key.replace(/_/g, "-").replace(/[A-Z]/g, (match) => `-${match.toLowerCase()}`);
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
    if (el && el.dataset) el.dataset.xySlot = slot;
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
    // Match on the canonical CSS property name so a snake_case key (`max_height`,
    // the Python API form), camelCase, and kebab all resolve. _applyStyle already
    // normalizes the author's key onto the element, so this guard must too —
    // otherwise the responsive max-height cap in _resize re-applies over an
    // explicit styles[legend] value on resize (browser-verified: 50px → plot
    // height). hasOwnProperty on the raw key alone missed the snake_case form.
    const want = this._stylePropertyName(property);
    for (const key of Object.keys(style)) {
      if (this._stylePropertyName(key) === want) return style[key];
    }
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
      if (this._destroyed) return;
      const governedRelease = this.canvas.dataset.xyCtx === "released";
      // _releaseContext marks the view lost synchronously before the browser
      // dispatches this event. Still run the full quiesce/telemetry path for
      // that first governed event; only ignore duplicate ungoverned losses.
      if (this._glLost && !governedRelease) return;
      this._glLost = true;
      // Governed releases already stamped "released"; anything else is a
      // browser-side eviction/driver reset (§28: the difference stays legible).
      if (!governedRelease) this.canvas.dataset.xyCtx = "lost";
      this._contextLossCount += 1;
      this._contextRecoveryError = null;
      this.root.dataset.xyContextState = "lost";
      // Quiesce every source of deferred GPU work, not only the draw RAF.
      // Incrementing seq makes pre-loss kernel/worker replies stale, so they
      // cannot populate the newly restored context with an old view.
      this.seq += 1;
      if (this._raf) cancelAnimationFrame(this._raf);
      this._raf = null;
      if (this._wheelZoomRaf) cancelAnimationFrame(this._wheelZoomRaf);
      this._wheelZoomRaf = null;
      this._pendingWheelZoom = null;
      this._cancelViewAnimation();
      clearTimeout(this._viewTimer);
      this._viewTimer = null;
      clearTimeout(this._rebinTimer);
      this._rebinTimer = null;
      this._viewRequestBurstStart = null;
      this._dispatchChartEvent("context_lost", {
        loss_count: this._contextLossCount,
      });
    });
    this._listen(this.canvas, "webglcontextrestored", () => {
      // A failed recovery replaced the canvas with the error message; a later
      // restore firing on the detached canvas must not resurrect GL state the
      // user can no longer see.
      if (this._destroyed || this._contextRecoveryError) return;
      // Old handles died with the context — drop them without delete calls.
      this._lutCache.clear();
      this.pickFbo = null;
      this.pickTex = null;
      try {
        this._initGl(this._payload);
      } catch (err) {
        this._glLost = true;
        this._contextRecoveryError = err;
        this.root.dataset.xyContextState = "failed";
        try { this._destroyGlResources(); } catch (_cleanupErr) {}
        this.gl = null;
        this._dispatchChartEvent("context_restore_failed", {
          loss_count: this._contextLossCount,
          message: err instanceof Error ? err.message : String(err),
        });
        this.root.textContent = "xy: WebGL2 context could not be restored.";
        return;
      }
      this._glLost = false;
      this._contextRestoreCount += 1;
      this._contextRecoveryError = null;
      this.root.dataset.xyContextState = "ready";
      this._scheduleViewRequest(this.view, { delay: 0 });
      this.draw();
      this._dropContextSnapshot(); // live frame is back; retire the stand-in
      this._dispatchChartEvent("context_restored", {
        loss_count: this._contextLossCount,
        restore_count: this._contextRestoreCount,
      });
    });
  }

  // Governed release: give this view's GL context back to the page on purpose
  // (WEBGL_lose_context), keeping total live contexts under the governor's
  // budget so the *browser* never LRU-evicts a visible chart. The retained
  // spec + payload rebuild everything on re-entry (§18/§27), riding the same
  // lost/restored machinery the lifecycle gate already exercises.
  _releaseContext() {
    if (this._destroyed || !this.gl || this._glLost || this.gl.isContextLost()) return false;
    const ext = this.gl.getExtension("WEBGL_lose_context");
    if (!ext) return false;
    this._snapshotBeforeRelease();
    this._ctxReleasedExt = ext;
    this._ctxReleases += 1;
    this._glLost = true; // synchronous: the lost *event* arrives as a task
    this.canvas.dataset.xyCtx = "released";
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
    ext.loseContext();
    return true;
  }

  // Freeze the current frame into a 2D stand-in before the GL context goes
  // away. This is what lets the governor release *visible* views: an
  // over-budget panel keeps showing its last frame as a static image
  // (matplotlib-style) instead of blanking, and pointer entry swaps the live
  // context back in. The draw must be synchronous and in the same task as the
  // copy — the default drawing buffer does not persist between frames.
  _snapshotBeforeRelease() {
    try {
      if (this._raf) cancelAnimationFrame(this._raf);
      this._raf = null;
      this._rafKeepPick = true; // pick FBO stays valid; only the color buffer is read
      this._drawNow();
      let snap = this._ctxSnapshot;
      if (!snap) {
        snap = this._ctxSnapshot = document.createElement("canvas");
        snap.dataset.xyCtxSnapshot = "";
      }
      snap.width = this.canvas.width;
      snap.height = this.canvas.height;
      snap.style.cssText = this.canvas.style.cssText;
      snap.style.pointerEvents = "none";
      snap.getContext("2d").drawImage(this.canvas, 0, 0);
      this.canvas.before(snap);
      // Chrome composites a lost-context canvas as an opaque broken-image
      // tile, which would sit on top of the stand-in. Events still reach the
      // root, so pointer-entry revival keeps working.
      this.canvas.style.visibility = "hidden";
    } catch (_err) {
      this._dropContextSnapshot(); // released view degrades to blank, as before
    }
  }

  _dropContextSnapshot() {
    this.canvas.style.visibility = "";
    if (this._ctxSnapshot) this._ctxSnapshot.remove();
    this._ctxSnapshot = null;
  }

  // Re-acquire on scroll-into-view. Governed releases undo via
  // restoreContext() -> the existing restored handler rebuilds; a real
  // browser eviction cannot be force-restored, so the canvas is swapped for a
  // fresh one and rebuilt from the retained spec + payload.
  _recoverContext() {
    if (this._destroyed || !this._glLost) return;
    this._ctxRecoveries += 1;
    if (this._ctxReleasedExt) {
      const ext = this._ctxReleasedExt;
      this._ctxReleasedExt = null;
      try {
        // Reserve before asking the browser to restore. The restored event is
        // asynchronous, so the pending reservation must count against later
        // recoveries in the same IntersectionObserver delivery.
        XY_CONTEXT_GOVERNOR.reserve(this);
        ext.restoreContext(); // restored event -> full rebuild
        return;
      } catch (_err) {
        XY_CONTEXT_GOVERNOR.cancel(this);
        // Extension refused (context was also evicted for real): fall through.
      }
    }
    this._rebuildEvictedContext();
  }

  _rebuildEvictedContext() {
    // The evicted context object is dead for good and a canvas keeps its
    // context forever, so recovery swaps in a fresh canvas (attributes
    // cloned, listeners retargeted) and rebuilds — the same §18/§27 rebuild
    // the restored path uses.
    const fresh = this.canvas.cloneNode(false);
    for (const record of this._listeners) {
      if (record.target === this.canvas) {
        this.canvas.removeEventListener(record.type, record.handler, record.options);
        fresh.addEventListener(record.type, record.handler, record.options);
        record.target = fresh;
      }
    }
    this.canvas.replaceWith(fresh);
    this.canvas = fresh;
    this._glLost = false;
    this._lutCache.clear();
    this.pickFbo = null;
    this.pickTex = null;
    try {
      this._initGl(this._payload);
    } catch (_err) {
      this._glLost = true;
      this.canvas.dataset.xyCtx = "lost";
      return; // context pressure persists; the next visibility pass retries
    }
    this._scheduleViewRequest(this.view, { delay: 0 });
    this.draw();
    this._dropContextSnapshot();
  }

  // Visibility feed for the governor: tracks least-recently-visible order and
  // re-acquires a released/evicted context when the chart scrolls back into
  // view (25% rootMargin = pre-warm hysteresis; release is demand-driven only,
  // so fast scrolling never thrashes contexts).
  _armContextVisibilityWatch() {
    // A released-while-visible view (snapshot stand-in) revives on pointer
    // entry — visibility alone can't distinguish it from its neighbors, and
    // touching a chart is the interaction signal that it needs to be live.
    this._listen(this.root, "pointerenter", () => {
      if (this._glLost && !this._destroyed) this._recoverContext();
    });
    if (typeof IntersectionObserver === "undefined") {
      this._ctxVisible = true; // no observer: never treat as releasable
      return;
    }
    this._ctxIo = new IntersectionObserver(
      (entries) => {
        const entry = entries[entries.length - 1];
        this._ctxVisible = entry.isIntersecting || entry.intersectionRatio > 0;
        if (this._ctxVisible) {
          this._ctxSeenSeq = XY_CONTEXT_GOVERNOR.seq++;
          if (this._glLost && !this._destroyed) this._recoverContext();
          if (this._healStaleTheme()) this.draw();
        }
      },
      { rootMargin: "25% 0px 25% 0px" },
    );
    this._ctxIo.observe(this.root);
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
    this.root.style.setProperty("--xy-legend-max-width", Math.max(40, p.w - 12) + "px");
    this.root.style.setProperty("--xy-legend-max-height", Math.max(40, p.h - 12) + "px");
    this.canvas.style.left = p.x + "px";
    this.canvas.style.top = p.y + "px";
    this.canvas.style.width = p.w + "px";
    this.canvas.style.height = p.h + "px";
    this.canvas.width = p.w * this.dpr;
    this.canvas.height = p.h * this.dpr;
    this.chrome.style.width = this.size.w + "px";
    this.chrome.style.height = this.size.h + "px";
    this.chrome.width = this.size.w * this.dpr;
    this.chrome.height = this.size.h * this.dpr;
    this.overlay.style.width = this.size.w + "px";
    this.overlay.style.height = this.size.h + "px";
    this.overlay.width = this.size.w * this.dpr;
    this.overlay.height = this.size.h * this.dpr;
    for (const lg of this._legends || []) {
      this._positionLegend(lg, lg.dataset.xyLegendLoc || "upper right");
    }
    this._positionReductionBadges();
    this._positionColorbar();
    this._fitModebar();
    this._pickDirty = true;
    this.draw();
    this._scheduleViewRequest();
  }

  _buildDom(el) {
    const s = this.spec;
    const root = document.createElement("div");
    root.className = "xy";
    root.style.cssText =
      `position:relative;width:${this.fluid ? "100%" : this.size.w + "px"};` +
      `height:${this.fluidH ? "100%" : this.size.h + "px"};` +
      `--xy-legend-max-width:${Math.max(40, this.plot.w - 12)}px;` +
      `--xy-legend-max-height:${Math.max(40, this.plot.h - 12)}px;` +
      (this.fluidH ? "min-height:120px;" : "") + // parent without a height -> visible floor
      "font:12px system-ui,sans-serif;user-select:none;";
    this._applySlot(root, "root");
    // A chart that brings its own backdrop (theme(background=) → inline root
    // background) marks itself so host-page overrides — VS Code's white
    // ipywidget card — can be scoped to charts that don't need it.
    if (root.style.background || root.style.backgroundColor) root.dataset.xyOwnBg = "";
    el.appendChild(root);
    this.root = root;
    // Visual chrome defaults live in one zero-specificity stylesheet so user
    // classes/styles win (§36). Only structural/state styles stay inline below.
    ensureChromeStylesheet(root);

    // Canvas pixels need a parallel semantic surface (§20). Keep the region
    // separate from the plot-area image role so the real toolbar descendants
    // remain exposed to assistive technology.
    let a11yId;
    do {
      a11yId = `xy-a11y-${++XY_A11Y_ID}`;
    } while (
      document.getElementById(`${a11yId}-summary`) || document.getElementById(`${a11yId}-live`)
    );
    root.setAttribute("role", "region");
    root.setAttribute("aria-label", s.title ? `Chart: ${s.title}` : "Interactive chart");
    this.a11ySummary = document.createElement("div");
    this.a11ySummary.id = `${a11yId}-summary`;
    this.a11ySummary.style.cssText = XY_SR_ONLY_STYLE;
    root.setAttribute("aria-describedby", this.a11ySummary.id);
    root.appendChild(this.a11ySummary);
    this.a11yLive = document.createElement("div");
    this.a11yLive.id = `${a11yId}-live`;
    this.a11yLive.setAttribute("role", "status");
    this.a11yLive.setAttribute("aria-live", "polite");
    this.a11yLive.setAttribute("aria-atomic", "true");
    this.a11yLive.style.cssText = XY_SR_ONLY_STYLE;
    root.appendChild(this.a11yLive);

    if (s.title) {
      const t = document.createElement("div");
      t.textContent = s.title;
      t.style.cssText = "position:absolute;top:6px;left:0;right:0;";
      this._applySlot(t, "title");
      root.appendChild(t);
    }

    this.chrome = document.createElement("canvas");
    this.chrome.style.cssText = "position:absolute;inset:0;pointer-events:none;";
    this._applySlot(this.chrome, "chrome");
    root.appendChild(this.chrome);

    this.canvas = document.createElement("canvas");
    // cursor is a defeatable stylesheet default keyed on data-xy-dragmode; only
    // structural geometry + touch-action stay inline here.
    this.canvas.style.cssText =
      `position:absolute;left:${this.plot.x}px;top:${this.plot.y}px;` +
      `width:${this.plot.w}px;height:${this.plot.h}px;touch-action:none;`;
    this._applySlot(this.canvas, "canvas");
    this.canvas.tabIndex = 0;
    this.canvas.setAttribute("role", "img");
    this.canvas.setAttribute("aria-describedby", this.a11ySummary.id);
    root.appendChild(this.canvas);

    // Annotation shapes (rules/bands/arrows/markers) draw here, ABOVE the
    // marks canvas: the exporters emit annotation marks after every data
    // trace, and a dense/opaque mark (heatmap) would otherwise bury them.
    // The chrome canvas below keeps the plot background and grid.
    this.overlay = document.createElement("canvas");
    this.overlay.style.cssText = "position:absolute;inset:0;pointer-events:none;";
    root.appendChild(this.overlay);

    this.labels = document.createElement("div");
    this.labels.style.cssText = "position:absolute;inset:0;pointer-events:none;";
    this._applySlot(this.labels, "labels");
    root.appendChild(this.labels);

    // Hover tooltip (§17) — DOM, so it's crisp and selectable (§7). Visual
    // styling is in the shared stylesheet; only position/state stays inline.
    this.tooltip = document.createElement("div");
    this.tooltip.style.cssText =
      "position:absolute;display:none;pointer-events:none;z-index:5;";
    this._applySlot(this.tooltip, "tooltip");
    this.tooltip.setAttribute("aria-hidden", "true");
    root.appendChild(this.tooltip);

    this._buildLegend(root);
    this._buildColorbar(root);
    this._buildReductionBadges(root);
  }

  _a11yAxisSummary(axisId, name) {
    const axis = this._axis(axisId);
    const label = axis.label ? `${name} axis (${axis.label})` : `${name} axis`;
    if (axis.kind === "category") {
      const categories = Array.isArray(axis.categories) ? axis.categories : [];
      if (!categories.length) return `${label} uses categories.`;
      const shown = categories.slice(0, 6).map((value) => String(value));
      const remaining = categories.length - shown.length;
      const suffix = remaining > 0 ? `, and ${remaining} more` : "";
      return `${label} has ${categories.length} categories: ${shown.join(", ")}${suffix}.`;
    }
    const range = axis.range || [];
    if (range.length < 2) return null;
    return `${label} ranges from ${fmtValue(range[0], axis.kind)} to ${fmtValue(range[1], axis.kind)}.`;
  }

  _a11ySummaryText() {
    const traces = Array.isArray(this.spec.traces) ? this.spec.traces : [];
    const parts = [this.spec.title ? `${this.spec.title}.` : "Interactive chart."];
    parts.push(`${traces.length} data series.`);
    const names = traces.map((trace) => trace && trace.name).filter(Boolean).slice(0, 6);
    if (names.length) parts.push(`Series: ${names.join(", ")}.`);
    const x = this._a11yAxisSummary("x", "X");
    const y = this._a11yAxisSummary("y", "Y");
    if (x) parts.push(x);
    if (y) parts.push(y);
    return parts.join(" ");
  }

  _initA11y() {
    if (!this.a11ySummary || !this.canvas) return;
    this.a11ySummary.textContent = this._a11ySummaryText();
    const instruction = this._pickable
      ? " Use Arrow keys to explore data points in series data order; Home and End jump to the first and last point; Escape closes the readout."
      : "";
    this.canvas.setAttribute("aria-label", `Plot area.${instruction}`);
  }

  _compactInt(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "0";
    return Math.round(n).toLocaleString();
  }

  _positionReductionBadges() {
    if (!this._badges) return;
    const rightInset = this.size.w - (this.plot.x + this.plot.w);
    const bottomInset = this.size.h - (this.plot.y + this.plot.h);
    this._badges.style.right = `${rightInset + 6}px`;
    this._badges.style.bottom = `${bottomInset + 6}px`;
  }

  _reductionBadgeItems() {
    const items = [];
    const traces = this.gpuTraces && this.gpuTraces.length
      ? this.gpuTraces
      : (this.spec.traces || []);
    for (const entry of traces) {
      const t = entry.trace || entry;
      if (t.tier !== "density" || !t.density) continue;
      const sample = entry.sampleOverlay && entry.sampleOverlay.sample
        ? entry.sampleOverlay.sample
        : t.density.sample;
      if (sample && Number(sample.n) > 0) {
        items.push(`sampled ${this._compactInt(sample.n)} of ${this._compactInt(sample.visible)}`);
      }
      // Standalone zoom refinement re-bins the sample in the worker — a
      // quality reduction vs a kernel re-bin, so it is badged (§28).
      if (entry._sampleRebinned) items.push("zoom re-binned from sample");
      if (t.density.channels_dropped) items.push("aggregated channels");
    }
    return items;
  }

  _refreshReductionBadges() {
    if (!this._badges) return;
    const items = this._reductionBadgeItems();
    this._badges.textContent = "";
    this._badges.hidden = items.length === 0;
    for (const item of items) {
      const badge = document.createElement("div");
      badge.textContent = item;
      this._applySlot(badge, "badge_item"); // visual defaults in the stylesheet
      this._badges.appendChild(badge);
    }
    this._positionReductionBadges();
  }

  _buildReductionBadges(root) {
    const items = this._reductionBadgeItems();
    const hasDensityTrace = (this.spec.traces || []).some((t) => t.tier === "density");
    if (!items.length && !hasDensityTrace) return;
    const box = document.createElement("div");
    box.style.cssText =
      "position:absolute;display:flex;flex-direction:column;align-items:flex-end;" +
      "pointer-events:none;z-index:4;";
    this._applySlot(box, "badge");
    root.appendChild(box);
    this._badges = box;
    this._refreshReductionBadges();
  }

  _buildLegend(root) {
    const s = this.spec;
    this._legends = [];
    const items = [];
    if (s.show_legend !== false) {
      for (const t of s.traces) {
        if (t.tier === "density") {
          items.push({ swatch: "gradient", cmap: t.density.colormap, name: t.name || "density" });
        } else if (t.color && t.color.mode === "categorical") {
          t.color.categories.forEach((cat, i) =>
            items.push({ swatch: t.color.palette[i], name: cat, symbol: t.kind === "scatter" ? (t.style?.symbol || "circle") : null, style: t.style || {} }));
        } else if (t.color && t.color.mode === "continuous") {
          items.push({ swatch: "gradient", cmap: t.color.colormap, name: t.name || "value" });
        } else if (t.name) {
          const c = (t.color && t.color.color) || (t.style && t.style.color);
          // Line-family kinds get a short line sample (honoring the dash), the
          // same handle the raster/SVG exporters draw — not a filled swatch.
          const line = ["line", "segments", "step", "stairs", "errorbar"].includes(t.kind);
          items.push({ swatch: c, name: t.name, symbol: t.kind === "scatter" ? (t.style?.symbol || "circle") : null, line, style: t.style || {} });
        }
      }
      if (items.length) this._legendBox(root, items, s.legend || {});
    }
    // Manually added Legend artists ship explicit items + their own loc, so a
    // second legend (e.g. one per line group) renders as its own box.
    for (const extra of s.extra_legends || []) {
      const mapped = (extra.items || []).map((it) => ({
        swatch: it.style && it.style.color,
        name: it.name,
        symbol: it.kind === "scatter" ? (it.style?.symbol || "circle") : null,
        line: ["line", "segments", "step", "stairs", "errorbar"].includes(it.kind),
        style: it.style || {},
      }));
      if (mapped.length) this._legendBox(root, mapped, extra);
    }
  }

  _legendBox(root, items, options) {
    const lg = document.createElement("div");
    const loc = options.loc || "upper right";
    const ncols = Math.max(1, Number(options.ncols) || 1);
    const horizontal = ncols > 1;
    lg.style.cssText = "position:absolute;" +
      `display:grid;grid-template-columns:repeat(${horizontal ? ncols : 1},max-content);` +
      "overflow:auto;";
    lg.dataset.xyLegendLoc = loc;
    this._positionLegend(lg, loc);
    this._applySlot(lg, "legend");
    if (options.title) {
      const title = document.createElement("div");
      title.textContent = String(options.title);
      title.style.fontWeight = "600";
      title.style.gridColumn = `1 / span ${horizontal ? ncols : 1}`;
      lg.appendChild(title);
    }
    for (const it of items) {
      const row = document.createElement("div");
      this._applySlot(row, "legend_item");
      const sw = document.createElement("span");
      // Swatch geometry is a stylesheet default; only the paint (dynamic per
      // series) stays inline, and it now has its own slot so it's classable.
      sw.style.display = "inline-block";
      sw.style.verticalAlign = "-1px";
      let bg = it.swatch;
      if (it.swatch === "gradient") {
        const stops = colormapStops(it.cmap);
        bg = `linear-gradient(90deg,${stops.map((c) => `rgb(${c[0]},${c[1]},${c[2]})`).join(",")})`;
        sw.style.background = bg;
      } else if (it.symbol) {
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", "0 0 18 14");
        svg.setAttribute("width", "18");
        svg.setAttribute("height", "14");
        const path = document.createElementNS(ns, "path");
        const paths = {
          square: "M4.5 2.5h9v9h-9z", diamond: "M9 2l5 5-5 5-5-5z",
          thin_diamond: "M9 2l3 5-3 5-3-5z",
          triangle: "M9 2l-5 10h10z", triangle_down: "M9 12L4 2h10z",
          triangle_left: "M4 7L14 2v10z", triangle_right: "M14 7L4 2v10z",
          plus_line: "M9 2v10M4 7h10", x_line: "M5 3l8 8M13 3l-8 8",
          cross: "M7.5 2h3v3.5H14v3h-3.5V12h-3V8.5H4v-3h3.5z",
          x: "M5.5 2L9 5.5 12.5 2 14 3.5 10.5 7 14 10.5 12.5 12 9 8.5 5.5 12 4 10.5 7.5 7 4 3.5z",
          pentagon: "M9 2.5L13.28 5.61 11.65 10.64H6.35L4.72 5.61z",
          hexagon: "M9 2L13.3 4.5v5L9 12l-4.3-2.5v-5z",
          star: "M9 2l1.5 3.1 3.5.5-2.5 2.5.6 3.5L9 10l-3.1 1.6.6-3.5L4 5.6l3.5-.5z"
        };
        const color = safeCssPaint(this.root, bg);
        if (it.symbol === "circle" || it.symbol === "point" || it.symbol === "pixel") {
          if (it.symbol === "pixel") path.setAttribute("d", "M8.5 6.5h1v1h-1z");
          else path.setAttribute("d", `M9 ${it.symbol === "point" ? 4.75 : 2.5}a${it.symbol === "point" ? 2.25 : 4.5} ${it.symbol === "point" ? 2.25 : 4.5} 0 1 0 0 ${it.symbol === "point" ? 4.5 : 9}a${it.symbol === "point" ? 2.25 : 4.5} ${it.symbol === "point" ? 2.25 : 4.5} 0 1 0 0 -${it.symbol === "point" ? 4.5 : 9}`);
        } else path.setAttribute("d", paths[it.symbol] || paths.square);
        path.setAttribute("fill", it.symbol.endsWith("_line") ? "none" : color);
        path.setAttribute("stroke", color);
        path.setAttribute("stroke-width", String(it.style?.stroke_width || 1));
        svg.appendChild(path);
        sw.appendChild(svg);
        sw.style.width = "18px";
        sw.style.height = "14px";
      } else if (it.line) {
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", "0 0 22 12");
        svg.setAttribute("width", "22");
        svg.setAttribute("height", "12");
        const ln = document.createElementNS(ns, "line");
        ln.setAttribute("x1", "1");
        ln.setAttribute("y1", "6");
        ln.setAttribute("x2", "21");
        ln.setAttribute("y2", "6");
        ln.setAttribute("stroke", safeCssPaint(this.root, bg));
        // ?? not ||: an explicit lw=0 keeps 0 and draws nothing, like the
        // exporters' dict-default and Matplotlib itself.
        ln.setAttribute("stroke-width", String(it.style?.width ?? 1.5));
        if (it.style?.dash && it.style.dash.length) ln.setAttribute("stroke-dasharray", it.style.dash.join(" "));
        svg.appendChild(ln);
        sw.appendChild(svg);
        sw.style.width = "22px";
        sw.style.height = "12px";
      } else {
        sw.style.background = safeCssPaint(this.root, bg);
      }
      this._applySlot(sw, "legend_swatch");
      row.appendChild(sw);
      row.appendChild(document.createTextNode(it.name));
      lg.appendChild(row);
    }
    root.appendChild(lg);
    this._legends.push(lg); // _resize refreshes each box's responsive anchor
    return lg;
  }

  _positionLegend(lg, loc) {
    if (!lg) return;
    // Responsive anchors flow through private custom properties consumed by a
    // zero-specificity rule. Author classes or component styles can still set
    // real left/right/top/bottom/transform declarations and win normally.
    const rightInset = this.size.w - (this.plot.x + this.plot.w);
    const h = loc.includes("left") ? "left" : loc.includes("right") ? "right" : "center";
    const v = loc.includes("upper") ? "upper" : loc.includes("lower") ? "lower" : "center";
    const left = h === "left" ? this.plot.x + 6 : h === "center" ? this.plot.x + this.plot.w / 2 : null;
    const right = h === "right" ? rightInset + 6 : null;
    const top = v === "upper" ? this.plot.y + 6 : v === "center" ? this.plot.y + this.plot.h / 2 : null;
    const bottom = v === "lower" ? this.size.h - (this.plot.y + this.plot.h) + 6 : null;
    lg.style.setProperty("--xy-legend-left", left == null ? "auto" : left + "px");
    lg.style.setProperty("--xy-legend-right", right == null ? "auto" : right + "px");
    lg.style.setProperty("--xy-legend-top", top == null ? "auto" : top + "px");
    lg.style.setProperty("--xy-legend-bottom", bottom == null ? "auto" : bottom + "px");
    const tx = h === "center" ? "-50%" : "0";
    const ty = v === "center" ? "-50%" : "0";
    lg.style.setProperty("--xy-legend-transform", `translate(${tx},${ty})`);
  }

  _buildColorbar(root) {
    const cb = this.spec.colorbar;
    if (!cb) return;
    const box = document.createElement("div");
    const horizontal = cb.orientation === "horizontal";
    box.style.cssText = "position:absolute;pointer-events:none;z-index:4;";
    this._applySlot(box, "colorbar");

    const bar = document.createElement("div");
    const levels = Math.max(0, Number(cb.levels) || 0);
    let gradient;
    if (levels > 0) {
      const lut = buildLutData(cb.colormap || "viridis");
      const bands = [];
      for (let index = 0; index < levels; index++) {
        const sample = Math.min(255, Math.round(255 * (index + 0.5) / levels));
        const color = `rgb(${lut[sample * 4]},${lut[sample * 4 + 1]},${lut[sample * 4 + 2]})`;
        bands.push(`${color} ${100 * index / levels}% ${100 * (index + 1) / levels}%`);
      }
      gradient = `linear-gradient(to ${horizontal ? "right" : "top"},${bands.join(",")})`;
    } else {
      const stops = colormapStops(cb.colormap || "viridis");
      gradient = `linear-gradient(to ${horizontal ? "right" : "top"},${stops.map((c) =>
        `rgb(${c[0]},${c[1]},${c[2]})`).join(",")})`;
    }
    bar.style.cssText = horizontal
      ? `position:absolute;inset:0 0 auto 0;height:${COLORBAR_THICKNESS}px;`
      : `position:absolute;inset:0 auto 0 0;width:${COLORBAR_THICKNESS}px;`;
    bar.style.setProperty("--xy-colorbar-gradient", gradient);
    this._applySlot(bar, "colorbar_bar");
    box.appendChild(bar);

    const domain = cb.domain || [0, 1];
    const lo = Number(domain[0]), hi = Number(domain[1]);
    const span = hi - lo || 1;
    const tickResult = linearTicks(lo, hi, 8);
    const hasExplicitTicks = Array.isArray(cb.ticks);
    const tickValues = hasExplicitTicks ? cb.ticks : tickResult.ticks;
    const tickStep = tickResult.step;
    for (const raw of tickValues) {
      const value = Number(raw);
      if (!Number.isFinite(value) || value < Math.min(lo, hi) || value > Math.max(lo, hi)) continue;
      const tick = document.createElement("span");
      tick.textContent = hasExplicitTicks ? fmtGeneral(value) : fmtLinear(value, tickStep);
      const fraction = (value - lo) / span;
      tick.style.cssText = horizontal
        ? `position:absolute;left:${100 * fraction}%;top:${COLORBAR_THICKNESS + 2}px;transform:translateX(-50%);white-space:nowrap;`
        : `position:absolute;left:${COLORBAR_THICKNESS + 5}px;top:${100 * (1 - fraction)}%;transform:translateY(-50%);white-space:nowrap;`;
      this._applySlot(tick, "colorbar_tick");
      box.appendChild(tick);
    }
    if (cb.label) {
      const label = document.createElement("span");
      label.textContent = String(cb.label);
      label.style.cssText = horizontal
        ? `position:absolute;left:50%;top:${COLORBAR_THICKNESS + 18}px;transform:translateX(-50%);white-space:nowrap;`
        : `position:absolute;left:${COLORBAR_THICKNESS + 40}px;top:50%;writing-mode:vertical-rl;transform:translateY(-50%) rotate(180deg);white-space:nowrap;`;
      this._applySlot(label, "colorbar_title");
      box.appendChild(label);
    }
    box.title = `${cb.label ? cb.label + ": " : ""}${domain[0]} – ${domain[1]}`;
    root.appendChild(box);
    this._colorbar = box;
    this._colorbarHorizontal = horizontal;
    this._positionColorbar();
  }

  _positionColorbar() {
    if (!this._colorbar) return;
    const horizontal = this._colorbarHorizontal;
    this._colorbar.style.left = (horizontal
      ? this.plot.x
      : this.plot.x + this.plot.w + this._rightAxisRoom + COLORBAR_GAP) + "px";
    this._colorbar.style.top = (horizontal
      ? this.plot.y + this.plot.h + (this._bottomAxisRoom || 8)
      : this.plot.y) + "px";
    this._colorbar.style.width = (horizontal ? this.plot.w : 66) + "px";
    this._colorbar.style.height = (horizontal ? 50 : Math.max(24, this.plot.h)) + "px";
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
    this.overlay.width = this.size.w * dpr;
    this.overlay.height = this.size.h * dpr;
    this.overlay.style.width = this.size.w + "px";
    this.overlay.style.height = this.size.h + "px";

    // Stay inside the page's context budget before acquiring (governor above):
    // at budget, the least-recently-visible off-screen view releases first.
    XY_CONTEXT_GOVERNOR.reserve(this);
    const gl = this.canvas.getContext("webgl2", {
      antialias: false, premultipliedAlpha: true, alpha: true,
    });
    if (!gl) {
      XY_CONTEXT_GOVERNOR.cancel(this);
      this.root.textContent = "xy: WebGL2 unavailable in this browser.";
      throw new Error("webgl2 unavailable");
    }
    this.gl = gl;
    XY_CONTEXT_GOVERNOR.acquired(this);
    this.canvas.dataset.xyCtx = "live";
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    // Shader programs compile lazily on first use (small-data audit #2): a
    // simple line chart links one program instead of paying seven unused
    // synchronous compile+links before its first paint.
    this._progCache = new Map();
    this._glPrograms = this._progCache; // deletion iterates the cache values

    // Fullscreen quad for density/heatmap, plus its VAO (a_corner at slot 0).
    this.quad = gl.createBuffer();
    this.quad._fcId = ++this._bufSeq;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
    this.quadVao = gl.createVertexArray();
    gl.bindVertexArray(this.quadVao);
    gl.enableVertexAttribArray(ATTR_SLOTS.a_corner);
    gl.vertexAttribPointer(ATTR_SLOTS.a_corner, 2, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(ATTR_SLOTS.a_corner, 0);
    gl.bindVertexArray(null);

    this.gpuTraces = this.spec.traces.map((t) => this._buildTrace(buffer, t));
    this._pickable = this.gpuTraces.some((g) => markOf(g.trace.kind).pointPick && g.tier !== "density");
    if (this._pickable) this._initPickTarget();
  }

  _prog(key, vs, fs) {
    let p = this._progCache.get(key);
    if (!p) {
      p = makeProgram(this.gl, vs, fs);
      this._progCache.set(key, p);
    }
    return p;
  }

  get pointProg() { return this._prog("point", POINT_VS, POINT_FS); }
  get pointSimpleProg() { return this._prog("point-simple", POINT_SIMPLE_VS, POINT_SIMPLE_FS); }
  get lineProg() { return this._prog("line", LINE_VS, LINE_FS); }
  get segmentProg() { return this._prog("segment", SEGMENT_VS, SEGMENT_FS); }
  get meshProg() { return this._prog("mesh", MESH_VS, MESH_FS); }
  get areaProg() { return this._prog("area", AREA_VS, AREA_FS); }
  get rectProg() { return this._prog("rect", RECT_VS, RECT_FS); }
  get barProg() { return this._prog("bar", BAR_VS, RECT_FS); }
  get pickProg() { return this._prog("pick", PICK_VS, PICK_FS); }
  get densityProg() { return this._prog("density", GRID_VS, DENSITY_FS); }
  get heatmapProg() { return this._prog("heatmap", GRID_VS, HEATMAP_FS); }

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
      const meta = this.spec.columns[d.buf];
      const raw = this._columnView(buffer, meta);
      const grid = d.enc === "log-u8" ? lodDecodeLogU8(raw, d.max) : raw;
      g.densityNormMax = d.max;
      g.density = {
        w: d.w, h: d.h, max: d.max, normMax: d.max, colormap: d.colormap,
        color: d.color ? parseColor(this.root, d.color, [0.3, 0.47, 0.66, 1]) : null,
        xRange: d.x_range, yRange: d.y_range,
        grid: lodCopyGrid(grid),
        tex: this._uploadGrid(grid, d.w, d.h, d.max),
        lut: this._lut(d.colormap),
      };
      g.sampleOverlay = this._buildDensitySample(t, d.sample, buffer);
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
      g._cpu.color = this._columnView(buffer, this.spec.columns[t.color.buf]);
      g.cBuf = this._upload(g._cpu.color);
      g.lut = this._lut(t.color.colormap);
    } else if (t.color && t.color.mode === "categorical") {
      g.colorMode = 2;
      g._cpu.color = this._columnView(buffer, this.spec.columns[t.color.buf]);
      g.cBuf = this._upload(g._cpu.color);
      g.lut = this._paletteLut(t.color.palette);
    }
    g.sizeMode = 0;
    g.size = (t.size && t.size.size) || 4.0;
    g.sizeRange = [2, 18];
    if (t.size && t.size.mode === "continuous") {
      g.sizeMode = 1;
      g._cpu.size = this._columnView(buffer, this.spec.columns[t.size.buf]);
      g.sBuf = this._upload(g._cpu.size);
      g.sizeRange = t.size.range_px;
    }
    this._pointMarkStyle(g, t);
  }

  // Point symbol + stroke (scatter). An omitted stroke color means "face":
  // use each point's resolved LUT/palette color, never a generic trace color.
  _pointMarkStyle(g, t) {
    const s = t.style || {};
    g.symbol = { circle: 0, square: 1, diamond: 2, triangle: 3, cross: 4, hexagon: 5, pentagon: 6, star: 7, triangle_down: 8, triangle_left: 9, triangle_right: 10, x: 11, point: 12, pixel: 13, thin_diamond: 14, plus_line: 15, x_line: 16 }[s.symbol] || 0;
    g.pointStrokeWidth = Number(s.stroke_width) || 0;
    g.pointStrokeFace = !s.stroke;
    g.pointStroke = s.stroke
      ? parseColor(this.root, s.stroke, [g.color[0], g.color[1], g.color[2], 1])
      : null;
  }

  _sampleTraceSpec(parentTrace, sample) {
    return {
      id: parentTrace.id,
      kind: "scatter",
      name: parentTrace.name,
      style: sample.style || parentTrace.style || {},
      tier: "sampled",
      x: sample.x && sample.x.col,
      y: sample.y && sample.y.col,
      x_axis: parentTrace.x_axis,
      y_axis: parentTrace.y_axis,
      color: sample.color,
      size: sample.size,
    };
  }

  _buildDensitySample(parentTrace, sample, buffer) {
    if (!sample || !sample.x || !sample.y || sample.x.col === undefined || sample.y.col === undefined) {
      return null;
    }
    const trace = this._sampleTraceSpec(parentTrace, sample);
    const g = {
      trace,
      tier: "sampled",
      xAxis: typeof parentTrace.x_axis === "string" ? parentTrace.x_axis : "x",
      yAxis: typeof parentTrace.y_axis === "string" ? parentTrace.y_axis : "y",
    };
    this._buildScatterMark(g, trace, buffer);
    g.win = {
      x0: sample.x_range[0], x1: sample.x_range[1],
      y0: sample.y_range[0], y1: sample.y_range[1],
    };
    g.sample = { n: sample.n, visible: sample.visible };
    return g;
  }

  _destroyDensitySample(g) {
    const s = g && g.sampleOverlay;
    if (!s || !this.gl) return;
    for (const b of [s.xBuf, s.yBuf, s.cBuf, s.sBuf, s.selBuf, s.dBuf]) {
      if (b) this.gl.deleteBuffer(b);
    }
    g.sampleOverlay = null;
  }

  _applyDensitySample(g, sample, buffers) {
    this._destroyDensitySample(g);
    if (!sample || !sample.x || !sample.y || sample.x.buf === undefined || sample.y.buf === undefined) {
      this._refreshReductionBadges();
      return;
    }
    const gl = this.gl;
    const trace = {
      id: g.trace.id,
      kind: "scatter",
      name: g.trace.name,
      style: sample.style || g.trace.style || {},
      tier: "sampled",
      x_axis: g.trace.x_axis,
      y_axis: g.trace.y_axis,
      color: sample.color,
      size: sample.size,
    };
    const s = {
      trace,
      tier: "sampled",
      xAxis: g.xAxis,
      yAxis: g.yAxis,
      xBuf: gl.createBuffer(),
      yBuf: gl.createBuffer(),
      xMeta: { offset: sample.x.offset, scale: sample.x.scale },
      yMeta: { offset: sample.y.offset, scale: sample.y.scale },
      n: Math.min(sample.x.len, sample.y.len),
      win: {
        x0: sample.x_range[0], x1: sample.x_range[1],
        y0: sample.y_range[0], y1: sample.y_range[1],
      },
      sample: { n: sample.n, visible: sample.visible },
      selActive: false,
      colorMode: 0,
      color: parseColor(this.root, sample.color && sample.color.color, [0.3, 0.47, 0.66, 1]),
      sizeMode: 0,
      size: (sample.size && sample.size.size) || 4.0,
      sizeRange: [2, 18],
    };
    gl.bindBuffer(gl.ARRAY_BUFFER, s.xBuf);
    gl.bufferData(gl.ARRAY_BUFFER, this._asF32(buffers[sample.x.buf]), gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, s.yBuf);
    gl.bufferData(gl.ARRAY_BUFFER, this._asF32(buffers[sample.y.buf]), gl.STATIC_DRAW);
    if (sample.color && sample.color.buf !== undefined) {
      s.colorMode = sample.color.mode === "continuous" ? 1 : 2;
      s.cBuf = gl.createBuffer();
      const colorValues = sample.color.dtype === "u8"
        ? this._asU8(buffers[sample.color.buf])
        : this._asF32(buffers[sample.color.buf]);
      s.cBuf._fcType = colorValues instanceof Uint8Array ? gl.UNSIGNED_BYTE : gl.FLOAT;
      gl.bindBuffer(gl.ARRAY_BUFFER, s.cBuf);
      gl.bufferData(gl.ARRAY_BUFFER, colorValues, gl.STATIC_DRAW);
      s.lut = sample.color.mode === "continuous"
        ? this._lut(sample.color.colormap)
        : this._paletteLut(sample.color.palette);
    }
    if (sample.size && sample.size.mode === "continuous") {
      s.sizeMode = 1;
      s.sBuf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, s.sBuf);
      gl.bufferData(gl.ARRAY_BUFFER, this._asF32(buffers[sample.size.buf]), gl.STATIC_DRAW);
      s.sizeRange = sample.size.range_px;
    }
    g.sampleOverlay = s;
    this._refreshReductionBadges();
  }

  _drawDensitySample(g, x0, x1, y0, y1, opacityScale = 1) {
    const s = g && g.sampleOverlay;
    if (!s || !s.n || !this._viewInside(s.win)) return;
    this._drawPoints(
      s,
      this._map(s.xMeta, x0, x1, s.xAxis),
      this._map(s.yMeta, y0, y1, s.yAxis),
      opacityScale
    );
  }

  // Resolve a validated `style.fill` gradient (wire: {space, dir, stops}) into
  // GPU uniform data. Stop colors resolve against the live DOM (var()/oklch/
  // named colors); `currentColor` means the mark's own resolved color, so the
  // one-liner `linear-gradient(currentColor, transparent)` follows the palette
  // and theme. Colors are premultiplied here and interpolated premultiplied in
  // the shader, so fades to transparent keep their hue.
  _resolveMarkFill(style, markColor) {
    const fill = style && style.fill;
    if (!fill || !Array.isArray(fill.stops) || fill.stops.length < 2) return null;
    const mode = fill.space === "plot" ? 2 : 1;
    const dir = { down: 0, up: 1, left: 2, right: 3 }[fill.dir] ?? 0;
    const count = Math.min(fill.stops.length, 8);
    const pos = new Float32Array(8);
    const colors = new Float32Array(32);
    for (let i = 0; i < count; i++) {
      const stop = fill.stops[i] || [];
      pos[i] = Math.min(Math.max(Number(stop[0]) || 0, 0), 1);
      const expr = String(stop[1] || "").trim();
      const c = expr.toLowerCase() === "currentcolor"
        ? markColor
        : parseColor(this.root, expr, markColor);
      colors[i * 4] = c[0] * c[3];
      colors[i * 4 + 1] = c[1] * c[3];
      colors[i * 4 + 2] = c[2] * c[3];
      colors[i * 4 + 3] = c[3];
    }
    return { mode, dir, count, pos, colors };
  }

  _setGradientUniforms(prog, grad) {
    const gl = this.gl;
    const u = (n) => uniformOf(gl, prog, n);
    if (!grad) {
      gl.uniform1i(u("u_gradMode"), 0);
      return;
    }
    gl.uniform1i(u("u_gradMode"), grad.mode);
    gl.uniform1i(u("u_gradDir"), grad.dir);
    gl.uniform1i(u("u_gradCount"), grad.count);
    gl.uniform1fv(u("u_gradPos"), grad.pos);
    gl.uniform4fv(u("u_gradColor"), grad.colors);
  }

  _fillOpacity(style, fallback = 1) {
    return Number(style.opacity ?? fallback) * Number(style.fill_opacity ?? 1);
  }

  _strokeOpacity(style, fallback = 1) {
    return Number(style.opacity ?? fallback) * Number(style.stroke_opacity ?? 1);
  }

  // Rect-family styling uniforms (rounded corners, stroke, gradient). Radius
  // and stroke width are CSS px -> device px; the stroke color ships
  // premultiplied to match the shader's blend space.
  _setRectStyleUniforms(prog, g) {
    const gl = this.gl;
    const u = (n) => uniformOf(gl, prog, n);
    gl.uniform2f(u("u_res"), this.canvas.width, this.canvas.height);
    const cr = g.cornerRadius || [0, 0];
    gl.uniform2f(u("u_radius"), cr[0] * this.dpr, cr[1] * this.dpr);
    gl.uniform1f(u("u_strokeWidth"), (g.strokeWidth || 0) * this.dpr);
    const sc = g.strokeColor || [0, 0, 0, 0];
    const sa = sc[3] * this._strokeOpacity(g.trace.style || {});
    gl.uniform4f(u("u_stroke"), sc[0] * sa, sc[1] * sa, sc[2] * sa, sa);
    this._setGradientUniforms(prog, g.grad);
  }

  // Shared rect-family mark styling (bar/column/histogram): rounded corners,
  // stroke, gradient. `corner_radius` is a scalar (all corners) or a
  // [tip, base] pair in mark space — (6, 0) rounds only the value end. A
  // stroke width with no stroke color borders in the mark color at full alpha.
  _rectMarkStyleGpu(g, t) {
    const s = t.style || {};
    const cr = s.corner_radius;
    g.cornerRadius = Array.isArray(cr)
      ? [Number(cr[0]) || 0, Number(cr[1]) || 0]
      : [Number(cr) || 0, Number(cr) || 0];
    g.strokeWidth = Number(s.stroke_width) || 0;
    const opaque = [g.color[0], g.color[1], g.color[2], 1];
    g.strokeColor = s.stroke ? parseColor(this.root, s.stroke, opaque) : opaque;
    g.grad = this._resolveMarkFill(s, g.color);
  }

  // curve:"smooth" resample for the polyline marks. Returns null unless the
  // trace opted in and the data qualifies; hover keeps reading the original
  // `_cpu` columns either way (`_nearestCpuIndex` limits to the source length).
  _smoothArrays(t, x, y, base, n) {
    if (!t.style || t.style.curve !== "smooth") return null;
    return xySmoothResample(x, y, base || null, n, 32768);
  }

  // Expand a step-styled polyline (style.step: "pre" | "mid" | "post") into
  // its drawn corner vertices. Runs after smoothing/decimation so canonical
  // inputs stay compact — both the initial build and every LOD tier swap must
  // apply it before upload. Returns null when the trace isn't stepped.
  _stepArrays(t, x, y, n) {
    const where = t.style && t.style.step;
    if (!where || n < 2) return null;
    const perGap = where === "mid" ? 3 : 2;
    const m = 1 + (n - 1) * perGap;
    const sx = new Float32Array(m);
    const sy = new Float32Array(m);
    sx[0] = x[0];
    sy[0] = y[0];
    let j = 1;
    for (let i = 1; i < n; i++) {
      if (where === "pre") {
        sx[j] = x[i - 1]; sy[j] = y[i]; j++;
        sx[j] = x[i]; sy[j] = y[i]; j++;
      } else if (where === "mid") {
        const mid = (x[i - 1] + x[i]) * 0.5;
        sx[j] = mid; sy[j] = y[i - 1]; j++;
        sx[j] = mid; sy[j] = y[i]; j++;
        sx[j] = x[i]; sy[j] = y[i]; j++;
      } else {
        sx[j] = x[i]; sy[j] = y[i - 1]; j++;
        sx[j] = x[i]; sy[j] = y[i]; j++;
      }
    }
    return { x: sx, y: sy, n: m };
  }

  _buildLineMark(g, t, buffer) {
    const x = this._columnView(buffer, this.spec.columns[t.x]);
    const y = this._columnView(buffer, this.spec.columns[t.y]);
    g.xMeta = { ...this.spec.columns[t.x] };
    g.yMeta = { ...this.spec.columns[t.y] };
    g.n = Math.min(x.length, y.length);
    g._cpu = { x, y, xMeta: g.xMeta, yMeta: g.yMeta };
    const sm = this._smoothArrays(t, x, y, null, g.n);
    const src = sm || { x, y, n: g.n };
    const st = this._stepArrays(t, src.x, src.y, src.n);
    const drawX = st ? st.x : src.x;
    const drawY = st ? st.y : src.y;
    g.xBuf = this._upload(drawX);
    g.yBuf = this._upload(drawY);
    g.n = st ? st.n : src.n;
    // Drawn (offset-encoded) vertices kept for the screen-space dash arc length.
    g._dashX = drawX;
    g._dashY = drawY;
    g.color = parseColor(this.root, t.style && t.style.color, [0.3, 0.47, 0.66, 1]);
  }

  _buildSegmentMark(g, t, buffer) {
    const x0 = this._columnView(buffer, this.spec.columns[t.x0]);
    const x1 = this._columnView(buffer, this.spec.columns[t.x1]);
    const y0 = this._columnView(buffer, this.spec.columns[t.y0]);
    const y1 = this._columnView(buffer, this.spec.columns[t.y1]);
    g.x0Meta = { ...this.spec.columns[t.x0] };
    g.x1Meta = { ...this.spec.columns[t.x1] };
    g.y0Meta = { ...this.spec.columns[t.y0] };
    g.y1Meta = { ...this.spec.columns[t.y1] };
    g.n = Math.min(x0.length, x1.length, y0.length, y1.length);
    g.x0Buf = this._upload(x0);
    g.x1Buf = this._upload(x1);
    g.y0Buf = this._upload(y0);
    g.y1Buf = this._upload(y1);
    g._segmentCpu = { x0, x1, y0, y1 };
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
    g._cpu = { x: x0, y: y1, xMeta: g.x0Meta, yMeta: g.y1Meta };
  }

  _buildMeshMark(g, t, buffer) {
    for (const name of ["x0", "x1", "x2", "y0", "y1", "y2"]) {
      const values = this._columnView(buffer, this.spec.columns[t[name]]);
      g[name + "Meta"] = { ...this.spec.columns[t[name]] };
      g[name + "Buf"] = this._upload(values);
      g.n = g.n === undefined ? values.length : Math.min(g.n, values.length);
    }
    g.color = parseColor(this.root, t.color && t.color.color, [0.3, 0.47, 0.66, 1]);
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
    const style = t.style || {};
    g.meshStrokeWidth = Number(style.stroke_width) || 0;
    g.meshStroke = parseColor(this.root, style.stroke || "transparent", [0, 0, 0, 0]);
  }

  // Hexbin ships cell centers plus one color value per cell; every hexagon
  // shares the same geometry (style hex_dx/hex_dy), so the six-triangle fan
  // expands here instead of on the wire. Vertices stay in the centers'
  // encoded space: stored = (value - offset) * scale, so a data-space delta
  // scales by meta.scale and the center columns' metas serve every vertex.
  // The ring must match HEX_RING in python/xy/_svg.py.
  _buildHexbinMark(g, t, buffer) {
    const cx = this._columnView(buffer, this.spec.columns[t.x]);
    const cy = this._columnView(buffer, this.spec.columns[t.y]);
    const xMeta = { ...this.spec.columns[t.x] };
    const yMeta = { ...this.spec.columns[t.y] };
    const n = Math.min(cx.length, cy.length);
    const style = t.style || {};
    const dx = (Number(style.hex_dx) || 0) * (xMeta.scale || 1);
    const dy = (Number(style.hex_dy) || 0) * (yMeta.scale || 1);
    const ringX = [0, dx / 2, dx / 2, 0, -dx / 2, -dx / 2, 0];
    const ringY = [-dy / 3, -dy / 6, dy / 6, dy / 3, dy / 6, -dy / 6, -dy / 3];
    const parts = {};
    for (const name of ["x0", "x1", "x2", "y0", "y1", "y2"]) parts[name] = new Float32Array(n * 6);
    for (let i = 0; i < n; i++) {
      const px = cx[i], py = cy[i];
      for (let k = 0; k < 6; k++) {
        const j = i * 6 + k;
        parts.x0[j] = px;
        parts.y0[j] = py;
        parts.x1[j] = px + ringX[k];
        parts.y1[j] = py + ringY[k];
        parts.x2[j] = px + ringX[k + 1];
        parts.y2[j] = py + ringY[k + 1];
      }
    }
    for (const name of ["x0", "x1", "x2"]) {
      g[name + "Meta"] = { ...xMeta };
      g[name + "Buf"] = this._upload(parts[name]);
    }
    for (const name of ["y0", "y1", "y2"]) {
      g[name + "Meta"] = { ...yMeta };
      g[name + "Buf"] = this._upload(parts[name]);
    }
    g.n = n * 6;
    g.color = parseColor(this.root, t.color && t.color.color, [0.3, 0.47, 0.66, 1]);
    g.colorMode = 0;
    if (t.color && (t.color.mode === "continuous" || t.color.mode === "categorical")) {
      g.colorMode = t.color.mode === "continuous" ? 1 : 2;
      const cval = this._columnView(buffer, this.spec.columns[t.color.buf]);
      const expanded = new Float32Array(n * 6);
      for (let i = 0; i < n; i++) expanded.fill(cval[i], i * 6, i * 6 + 6);
      g.cBuf = this._upload(expanded);
      g.lut = t.color.mode === "continuous" ? this._lut(t.color.colormap) : this._paletteLut(t.color.palette);
    }
    g.meshStrokeWidth = Number(style.stroke_width) || 0;
    g.meshStroke = parseColor(this.root, style.stroke || "transparent", [0, 0, 0, 0]);
  }

  _buildAreaMark(g, t, buffer) {
    const x = this._columnView(buffer, this.spec.columns[t.x]);
    const y = this._columnView(buffer, this.spec.columns[t.y]);
    const base = this._columnView(buffer, this.spec.columns[t.base]);
    g.xMeta = { ...this.spec.columns[t.x] };
    g.yMeta = { ...this.spec.columns[t.y] };
    g.baseMeta = { ...this.spec.columns[t.base] };
    g.n = Math.min(x.length, y.length, base.length);
    g._cpu = { x, y, base, xMeta: g.xMeta, yMeta: g.yMeta };
    const sm = this._smoothArrays(t, x, y, base, g.n);
    g.xBuf = this._upload(sm ? sm.x : x);
    g.yBuf = this._upload(sm ? sm.y : y);
    g.baseBuf = this._upload(sm ? sm.extra : base);
    if (sm) g.n = sm.n;
    g._dashX = sm ? sm.x : x;
    g._dashY = sm ? sm.y : y;
    g.color = parseColor(this.root, t.style && t.style.color, [0.3, 0.47, 0.66, 1]);
    g.lineColor = parseColor(this.root, t.style && (t.style.line_color || t.style.color), g.color);
    g.grad = this._resolveMarkFill(t.style, g.color);
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
    this._rectMarkStyleGpu(g, t);
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
    this._rectMarkStyleGpu(g, t);
  }

  _buildHeatmapMark(g, t, buffer) {
    const h = t.heatmap;
    const truecolor = Array.isArray(h.rgba_bufs);
    const grid = truecolor
      ? h.rgba_bufs.map((index) => this._columnView(buffer, this.spec.columns[index]))
      : this._columnView(buffer, this.spec.columns[h.buf]);
    g.heatmap = {
      w: h.w,
      h: h.h,
      xRange: h.x_range,
      yRange: h.y_range,
      colormap: h.colormap,
      truecolor,
      tex: truecolor ? this._uploadRgbaGrid(grid, h.w, h.h) : this._uploadHeatmapGrid(grid, h.w, h.h),
      lut: truecolor ? null : this._lut(h.colormap),
    };
    if (!truecolor) g._cpuHeatmap = { grid };
  }

  _uploadRgbaGrid(channels, w, h) {
    const gl = this.gl;
    const tex = gl.createTexture();
    const data = new Uint8Array(w * h * 4);
    for (let index = 0; index < w * h; index++) {
      for (let channel = 0; channel < 4; channel++) {
        data[index * 4 + channel] = Math.round(255 * Math.max(0, Math.min(1, channels[channel][index])));
      }
    }
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return tex;
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
    // Packed layout: one blob, columns addressed by global byte_offset.
    // Split layout (§29 first paint): `buffer` is a list of per-column
    // buffers and the column entry carries `buf`, its list index. A
    // disagreement between spec and transport is a bug — fail loudly rather
    // than render from misaligned bytes.
    const split = Array.isArray(buffer);
    if (split !== Number.isInteger(meta.buf)) {
      throw new Error(
        split
          ? "xy: transport delivered a buffer list but the spec column has no wire-buffer index"
          : "xy: spec column carries a wire-buffer index but the transport delivered one blob",
      );
    }
    const span = xyByteSpan(split ? buffer[meta.buf] : buffer, "chart payload");
    const relativeOffset = Number(meta.byte_offset);
    const length = Number(meta.len);
    if (!Number.isSafeInteger(relativeOffset) || relativeOffset < 0 ||
        !Number.isSafeInteger(length) || length < 0) {
      throw new RangeError("column offset/length must be non-negative safe integers");
    }
    const bytesPerElement = meta.dtype === "u8" ? 1 : 4;
    const absoluteOffset = span.byteOffset + relativeOffset;
    const end = relativeOffset + length * bytesPerElement;
    if (end > span.byteLength) throw new RangeError("column extends past chart payload");
    if (absoluteOffset % bytesPerElement !== 0) throw new RangeError("column is misaligned");
    if (meta.dtype === "u8") return new Uint8Array(span.buffer, absoluteOffset, length);
    return new Float32Array(span.buffer, absoluteOffset, length);
  }

  _upload(view) {
    const gl = this.gl;
    const buf = gl.createBuffer();
    // Identity tag for VAO config signatures: a replaced buffer (data update,
    // drill swap) gets a new id, so any VAO built over the old one rebuilds.
    buf._fcId = ++this._bufSeq;
    buf._fcType = view instanceof Uint8Array ? gl.UNSIGNED_BYTE : gl.FLOAT;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, view, gl.STATIC_DRAW);
    return buf;
  }

  // -- vertex-array objects ---------------------------------------------------
  //
  // One VAO per (trace × draw-config). Attribute slots are fixed at link time
  // (ATTR_SLOTS in 40_gl.js), so a VAO built over a trace's buffers is valid
  // for every program that draws them (point + pick share one). `parts` is the
  // config signature — buffer ids plus the on/off state of optional channels —
  // and the VAO is rebuilt only when it changes. This removes the per-frame
  // getAttribLocation + enable + pointer + divisor churn (renderer audit #1),
  // and because VAOs isolate attribute-enable state per draw, the old
  // "disable every leftover attrib" loops (and their per-frame
  // gl.getParameter(MAX_VERTEX_ATTRIBS) driver round-trip) go away entirely.
  _bindVao(g, key, parts, setup) {
    const gl = this.gl;
    if (!g._vaos) g._vaos = new Map();
    const sig = parts.join("|");
    let entry = g._vaos.get(key);
    if (!entry || entry.sig !== sig) {
      if (entry) gl.deleteVertexArray(entry.vao);
      const vao = gl.createVertexArray();
      gl.bindVertexArray(vao);
      setup();
      entry = { vao, sig };
      g._vaos.set(key, entry);
    } else {
      gl.bindVertexArray(entry.vao);
    }
  }

  _deleteVaos(g) {
    if (!g || !g._vaos) return;
    const gl = this.gl;
    if (gl) for (const { vao } of g._vaos.values()) gl.deleteVertexArray(vao);
    g._vaos = null;
  }

  // Enable slot + pointer into `buf` — only ever called inside a _bindVao
  // setup closure, so the state lands in that VAO, not global state.
  _vaoAttr(slot, buf, byteOffset, divisor, size = 1) {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.enableVertexAttribArray(slot);
    gl.vertexAttribPointer(slot, size, buf._fcType || gl.FLOAT, false, 0, byteOffset);
    gl.vertexAttribDivisor(slot, divisor);
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

  // `keepPick` marks a frame whose ONLY trigger is hover-highlight state: the
  // highlight lives in the color pass, so the pick framebuffer's geometry/view
  // snapshot stays valid and the frame must not invalidate it. Coalescing is
  // conservative: if any caller of a pending frame needs invalidation, the
  // frame invalidates (§17 — steady hover must not re-render N-point picks).
  draw(keepPick = false) {
    if (this._destroyed || this._glLost || !this.gl) return;
    this._updateZoomMenuLabel?.();
    if (this._raf) {
      this._rafKeepPick = this._rafKeepPick && keepPick;
      return;
    }
    this._rafKeepPick = keepPick;
    this._raf = requestAnimationFrame(() => {
      this._raf = null;
      if (this._destroyed) return;
      this._drawNow();
    });
  }


  _drawNow() {
    if (this._destroyed || !this.gl || this._glLost) return;
    this._healStaleTheme();
    const gl = this.gl;
    const { x0, x1, y0, y1 } = this.view;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    // Always transparent: this canvas sits ABOVE the chrome canvas over the
    // plot rect, so an opaque --chart-bg clear here would occlude everything
    // chrome draws inside the plot (grid, bands, rules, arrows). The plot
    // background paints at the bottom of the stack in _drawChrome instead.
    gl.clearColor(0, 0, 0, 0);
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
    // Hover-only frames leave the pick snapshot valid (see draw()); direct
    // _drawNow() callers never set the flag, so they invalidate as before.
    if (!this._rafKeepPick) this._pickDirty = true;
    this._rafKeepPick = false;
    this._drawChrome();
    this._renderLassoSelection?.();
  }

  // Centralized clock seam for animation state machines. Production uses the
  // browser's monotonic clock; deterministic render probes can replace this
  // private method without relying on platform-specific writability of
  // performance.now.
  _now() {
    return performance.now();
  }


  _drawPoints(g, xm, ym, opacityScale = 1) {
    const simple =
      g.colorMode === 0 && g.sizeMode === 0 && !g.selActive &&
      (g.symbol || 0) === 0 && (g.pointStrokeWidth || 0) <= 0 &&
      Math.max(g.lodBlendShown ?? 0, g.lodBlend ?? 0) <= 0.001;
    if (simple) {
      this._drawSimplePoints(g, xm, ym, opacityScale);
      return;
    }
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
    const markOpacity = this._fillOpacity(g.trace.style, 0.8) * opacityScale;
    gl.uniform1f(u("u_opacity"), markOpacity);
    gl.uniform1f(u("u_selectedOpacity"), this._markStateNumber("selected", "opacity", 1));
    gl.uniform1f(u("u_unselectedOpacity"), this._markStateNumber("unselected", "opacity", 0.12));
    // Optional selected/unselected recolor (§34): .a=1 tints, .a=0 keeps native.
    const stateColor = (loc, expr) => {
      const c = expr ? parseColor(this.root, expr, [0, 0, 0, 1]) : null;
      gl.uniform4f(loc, c ? c[0] : 0, c ? c[1] : 0, c ? c[2] : 0, c ? 1 : 0);
    };
    stateColor(u("u_selColor"), this._markStateValue("selected", "color"));
    stateColor(u("u_unselColor"), this._markStateValue("unselected", "color"));
    const [r, gg, b] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, 1);
    gl.uniform1i(u("u_symbol"), g.symbol || 0);
    const sc = g.pointStroke;
    const strokeAlpha = sc
      ? sc[3] * this._strokeOpacity(g.trace.style, 0.8) * opacityScale
      : 0;
    gl.uniform1f(u("u_ptStrokeWidth"), (g.pointStrokeWidth || 0) * this.dpr);
    gl.uniform1i(u("u_ptStrokeFace"), g.pointStrokeFace ? 1 : 0);
    gl.uniform4f(u("u_ptStroke"), sc ? sc[0] * strokeAlpha : 0, sc ? sc[1] * strokeAlpha : 0,
      sc ? sc[2] * strokeAlpha : 0, strokeAlpha);

    gl.uniform1i(u("u_selActive"), g.selActive ? 1 : 0);
    const colorOn = g.colorMode !== 0 && g.cBuf;
    const sizeOn = g.sizeMode === 1 && g.sBuf;
    const selOn = g.selActive && g.selBuf;
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
      const now = this._now();
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
    const blendOn = blend > 0.001 && g.dBuf && g.dlut;
    if (blendOn) {
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, g.dlut);
    }
    gl.uniform1i(u("u_dlut"), 1); // sampler must always point at a valid unit

    this._bindVao(
      g,
      "points",
      [
        g.xBuf._fcId, g.yBuf._fcId,
        colorOn ? g.cBuf._fcId : 0,
        sizeOn ? g.sBuf._fcId : 0,
        selOn ? g.selBuf._fcId : 0,
        blendOn ? g.dBuf._fcId : 0,
      ],
      () => {
        this._vaoAttr(ATTR_SLOTS.ax, g.xBuf, 0, 0);
        this._vaoAttr(ATTR_SLOTS.ay, g.yBuf, 0, 0);
        if (colorOn) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 0);
        if (sizeOn) this._vaoAttr(ATTR_SLOTS.a_sval, g.sBuf, 0, 0);
        if (selOn) this._vaoAttr(ATTR_SLOTS.a_sel, g.selBuf, 0, 0);
        if (blendOn) this._vaoAttr(ATTR_SLOTS.a_dval, g.dBuf, 0, 0);
      }
    );
    // Generic (constant) attribute values are context state, not VAO state —
    // set the disabled channels' fallbacks each draw (no driver lookups).
    if (!colorOn) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
    if (!sizeOn) gl.vertexAttrib1f(ATTR_SLOTS.a_sval, 0.5);
    if (!selOn) gl.vertexAttrib1f(ATTR_SLOTS.a_sel, 1.0);
    if (!blendOn) gl.vertexAttrib1f(ATTR_SLOTS.a_dval, 0);
    gl.drawArrays(gl.POINTS, 0, g.n);
  }

  _drawSimplePoints(g, xm, ym, opacityScale = 1) {
    const gl = this.gl;
    const prog = this.pointSimpleProg;
    gl.useProgram(prog);
    const u = (n) => uniformOf(gl, prog, n);
    gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
    gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
    this._setAxisUniforms(prog, "u_x", g.xMeta, g.xAxis);
    this._setAxisUniforms(prog, "u_y", g.yMeta, g.yAxis);
    gl.uniform1f(u("u_dpr"), this.dpr);
    gl.uniform1f(u("u_size"), g.size);
    const [r, gg, b] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, this._fillOpacity(g.trace.style, 0.8) * opacityScale);
    this._bindVao(
      g,
      "points-simple",
      [g.xBuf._fcId, g.yBuf._fcId],
      () => {
        this._vaoAttr(ATTR_SLOTS.ax, g.xBuf, 0, 0);
        this._vaoAttr(ATTR_SLOTS.ay, g.yBuf, 0, 0);
      }
    );
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

    this._bindVao(g, "hover", [g.xBuf._fcId, g.yBuf._fcId], () => {
      this._vaoAttr(ATTR_SLOTS.ax, g.xBuf, 0, 0);
      this._vaoAttr(ATTR_SLOTS.ay, g.yBuf, 0, 0);
    });
    gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
    gl.vertexAttrib1f(ATTR_SLOTS.a_sval, 0.5);
    gl.vertexAttrib1f(ATTR_SLOTS.a_sel, 1);
    gl.vertexAttrib1f(ATTR_SLOTS.a_dval, 0);
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
    gl.uniform1f(u("u_opacity"), this._fillOpacity(g.trace.style) * opacityScale);
    const constant = d.color;
    gl.uniform1i(u("u_constantColor"), constant ? 1 : 0);
    gl.uniform4f(u("u_color"), ...(constant || [1, 1, 1, 1]));
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, d.tex);
    gl.uniform1i(u("u_grid"), 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, d.lut);
    gl.uniform1i(u("u_lut"), 1);
    gl.bindVertexArray(this.quadVao);
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
    // Grid row/column 0 anchors to the bottom/left edge of the grid rect in
    // *display* orientation — the raster/SVG exporters' convention (the shim's
    // imshow pre-flips rows for origin='upper' assuming it). A reversed axis
    // flips the data direction, not the buffer, so swap the sampled range to
    // keep the anchoring; without this an inverted-y imshow rendered upside
    // down on canvas while every export of the same spec was upright.
    const xrev = (vx0 ?? x0) > (vx1 ?? x1);
    const yrev = (vy0 ?? y0) > (vy1 ?? y1);
    gl.uniform4f(
      u("u_gridRange"),
      h.xRange[xrev ? 1 : 0], h.xRange[xrev ? 0 : 1],
      h.yRange[yrev ? 1 : 0], h.yRange[yrev ? 0 : 1],
    );
    gl.uniform1f(u("u_opacity"), this._fillOpacity(g.trace.style));
    gl.uniform1i(u("u_truecolor"), h.truecolor ? 1 : 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, h.tex);
    gl.uniform1i(u("u_grid"), 0);
    if (!h.truecolor) {
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, h.lut);
      gl.uniform1i(u("u_lut"), 1);
    }
    gl.bindVertexArray(this.quadVao);
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
    const strokeOpacity = this._strokeOpacity(g.trace.style) * (opacity ?? 1);
    gl.uniform4f(u("u_color"), r, gg, b, a * strokeOpacity);
    const dashed = this._lineDash(g);
    this._bindVao(
      g,
      "line",
      dashed ? [g.xBuf._fcId, g.yBuf._fcId, g._lenBuf._fcId] : [g.xBuf._fcId, g.yBuf._fcId],
      () => {
        this._vaoAttr(ATTR_SLOTS.ax0, g.xBuf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ax1, g.xBuf, 4, 1);
        this._vaoAttr(ATTR_SLOTS.ay0, g.yBuf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ay1, g.yBuf, 4, 1);
        if (dashed) {
          this._vaoAttr(ATTR_SLOTS.a_len0, g._lenBuf, 0, 1);
          this._vaoAttr(ATTR_SLOTS.a_len1, g._lenBuf, 4, 1);
        }
      }
    );
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n - 1);
  }

  _drawSegments(g, xm, ym) {
    if (g.n < 1) return;
    const gl = this.gl;
    const prog = this.segmentProg;
    gl.useProgram(prog);
    const u = (n) => uniformOf(gl, prog, n);
    gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
    gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
    this._setAxisUniforms(prog, "u_x0", g.x0Meta, g.xAxis);
    this._setAxisUniforms(prog, "u_x1", g.x1Meta, g.xAxis);
    this._setAxisUniforms(prog, "u_y0", g.y0Meta, g.yAxis);
    this._setAxisUniforms(prog, "u_y1", g.y1Meta, g.yAxis);
    gl.uniform2f(u("u_res"), this.canvas.width, this.canvas.height);
    gl.uniform1f(u("u_width"), (g.trace.style.width ?? 1.5) * this.dpr);
    const [r, gg, b, a] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, a * this._strokeOpacity(g.trace.style));
    gl.uniform1i(u("u_colorMode"), g.colorMode || 0);
    const dashed = this._segmentDash(g, prog);
    if (g.colorMode && g.lut) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, g.lut);
      gl.uniform1i(u("u_lut"), 0);
    }
    this._bindVao(
      g,
      "segment",
      [g.x0Buf._fcId, g.x1Buf._fcId, g.y0Buf._fcId, g.y1Buf._fcId,
        g.colorMode ? g.cBuf._fcId : 0,
        dashed ? g._segmentDashOffsetBuf._fcId : 0,
        dashed ? g._segmentDashDirBuf._fcId : 0],
      () => {
        this._vaoAttr(ATTR_SLOTS.ax0, g.x0Buf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ax1, g.x1Buf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ay0, g.y0Buf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ay1, g.y1Buf, 0, 1);
        if (g.colorMode) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 1);
        if (dashed) {
          this._vaoAttr(ATTR_SLOTS.a_dash0, g._segmentDashOffsetBuf, 0, 1);
          this._vaoAttr(ATTR_SLOTS.a_dashDir, g._segmentDashDirBuf, 0, 1);
        }
      }
    );
    if (!g.colorMode) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n);
  }

  _segmentDash(g, prog) {
    const gl = this.gl;
    const u = (n) => uniformOf(gl, prog, n);
    const dash = g.trace.style && g.trace.style.dash;
    const cpu = g._segmentCpu;
    if (!dash || !dash.length || !cpu) {
      gl.uniform1i(u("u_dashCount"), 0);
      return false;
    }
    const n = g.n;
    const offsets = g._segmentDashOffsets?.length === n
      ? g._segmentDashOffsets : (g._segmentDashOffsets = new Float32Array(n));
    const directions = g._segmentDashDirections?.length === n
      ? g._segmentDashDirections : (g._segmentDashDirections = new Float32Array(n));
    const k0 = new Array(n), k1 = new Array(n), lengths = new Float32Array(n);
    const adjacency = new Map();
    const add = (key, index) => {
      const edges = adjacency.get(key);
      if (edges) edges.push(index); else adjacency.set(key, [index]);
    };
    const key = (x, y) => `${Math.round(x * 1000)},${Math.round(y * 1000)}`;
    const dpr = this.dpr;
    for (let i = 0; i < n; i++) {
      const x0 = this._dataPx(g.xAxis, this._decodeValue(cpu.x0, g.x0Meta, i));
      const x1 = this._dataPx(g.xAxis, this._decodeValue(cpu.x1, g.x1Meta, i));
      const y0 = this._dataPx(g.yAxis, this._decodeValue(cpu.y0, g.y0Meta, i));
      const y1 = this._dataPx(g.yAxis, this._decodeValue(cpu.y1, g.y1Meta, i));
      k0[i] = key(x0, y0); k1[i] = key(x1, y1);
      lengths[i] = Math.hypot(x1 - x0, y1 - y0) * dpr;
      add(k0[i], i); add(k1[i], i);
    }
    const visited = new Uint8Array(n);
    const walk = (start) => {
      let current = start, accumulated = 0;
      while (true) {
        const edge = (adjacency.get(current) || []).find((index) => !visited[index]);
        if (edge === undefined) break;
        visited[edge] = 1;
        if (k0[edge] === current) {
          offsets[edge] = accumulated;
          directions[edge] = 1;
          current = k1[edge];
        } else {
          offsets[edge] = accumulated + lengths[edge];
          directions[edge] = -1;
          current = k0[edge];
        }
        accumulated += lengths[edge];
      }
    };
    for (const [node, edges] of adjacency) if (edges.length === 1) walk(node);
    for (let i = 0; i < n; i++) if (!visited[i]) walk(k0[i]);
    const upload = (buffer, values) => {
      if (!buffer) return this._upload(values);
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, values, gl.DYNAMIC_DRAW);
      return buffer;
    };
    g._segmentDashOffsetBuf = upload(g._segmentDashOffsetBuf, offsets);
    g._segmentDashDirBuf = upload(g._segmentDashDirBuf, directions);
    const pattern = new Float32Array(8);
    const count = Math.min(dash.length, 8);
    let period = 0;
    for (let i = 0; i < count; i++) {
      pattern[i] = Number(dash[i]) * dpr;
      period += pattern[i];
    }
    gl.uniform1i(u("u_dashCount"), count);
    gl.uniform1fv(u("u_dashArr"), pattern);
    gl.uniform1f(u("u_dashPeriod"), Math.max(period, 1e-3));
    return true;
  }

  _drawMesh(g, xm, ym) {
    if (g.n < 1) return;
    const gl = this.gl;
    const prog = this.meshProg;
    gl.useProgram(prog);
    const u = (n) => uniformOf(gl, prog, n);
    gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
    gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
    for (const name of ["x0", "x1", "x2"]) this._setAxisUniforms(prog, "u_" + name, g[name + "Meta"], g.xAxis);
    for (const name of ["y0", "y1", "y2"]) this._setAxisUniforms(prog, "u_" + name, g[name + "Meta"], g.yAxis);
    gl.uniform1i(u("u_colorMode"), g.colorMode || 0);
    gl.uniform1f(u("u_opacity"), this._fillOpacity(g.trace.style));
    gl.uniform4f(u("u_color"), g.color[0], g.color[1], g.color[2], 1);
    const stroke = g.meshStroke || [0, 0, 0, 0];
    const strokeAlpha = stroke[3] * this._strokeOpacity(g.trace.style);
    gl.uniform4f(u("u_stroke"), stroke[0] * strokeAlpha, stroke[1] * strokeAlpha,
      stroke[2] * strokeAlpha, strokeAlpha);
    gl.uniform1f(u("u_strokeWidth"), g.meshStrokeWidth || 0);
    if (g.colorMode && g.lut) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, g.lut);
      gl.uniform1i(u("u_lut"), 0);
    }
    const parts = ["x0", "x1", "x2", "y0", "y1", "y2"].map((name) => g[name + "Buf"]._fcId);
    parts.push(g.colorMode ? g.cBuf._fcId : 0);
    this._bindVao(g, "mesh", parts, () => {
      for (const name of ["x0", "x1", "x2", "y0", "y1", "y2"]) {
        this._vaoAttr(ATTR_SLOTS["a" + name], g[name + "Buf"], 0, 1);
      }
      if (g.colorMode) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 1);
    });
    if (!g.colorMode) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
    gl.drawArraysInstanced(gl.TRIANGLES, 0, 3, g.n);
  }

  // Dash setup for a line/area outline: recompute per-vertex cumulative
  // screen-space arc length (device px) for the current view, upload it, and
  // set the dash-pattern uniforms. Returns false (u_dashCount=0) for solid
  // lines. Cost is O(vertices) per draw, dashed traces only.
  _lineDash(g) {
    const gl = this.gl;
    const u = (n) => uniformOf(gl, this.lineProg, n);
    const dash = g.trace.style && g.trace.style.dash;
    if (!dash || !dash.length || !g._dashX) {
      gl.uniform1i(u("u_dashCount"), 0);
      return false;
    }
    const n = g.n;
    if (!g._lenArr || g._lenArr.length !== n) g._lenArr = new Float32Array(n);
    const lens = g._lenArr;
    const dpr = this.dpr;
    let px = this._dataPx(g.xAxis, this._decodeValue(g._dashX, g.xMeta, 0));
    let py = this._dataPx(g.yAxis, this._decodeValue(g._dashY, g.yMeta, 0));
    let acc = 0;
    lens[0] = 0;
    for (let i = 1; i < n; i++) {
      const nx = this._dataPx(g.xAxis, this._decodeValue(g._dashX, g.xMeta, i));
      const ny = this._dataPx(g.yAxis, this._decodeValue(g._dashY, g.yMeta, i));
      if (Number.isFinite(nx) && Number.isFinite(ny) && Number.isFinite(px) && Number.isFinite(py)) {
        acc += Math.hypot(nx - px, ny - py) * dpr;
      }
      lens[i] = acc;
      px = nx;
      py = ny;
    }
    if (!g._lenBuf) g._lenBuf = this._upload(lens);
    else {
      gl.bindBuffer(gl.ARRAY_BUFFER, g._lenBuf);
      gl.bufferData(gl.ARRAY_BUFFER, lens, gl.DYNAMIC_DRAW);
    }
    const arr = new Float32Array(8);
    let period = 0;
    const count = Math.min(dash.length, 8);
    for (let i = 0; i < count; i++) {
      arr[i] = dash[i] * dpr;
      period += arr[i];
    }
    gl.uniform1i(u("u_dashCount"), count);
    gl.uniform1fv(u("u_dashArr"), arr);
    gl.uniform1f(u("u_dashPeriod"), Math.max(period, 1e-3));
    return true;
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
    gl.uniform4f(u("u_color"), r, gg, b, a * this._fillOpacity(g.trace.style, 0.35));
    gl.uniform2f(u("u_res"), this.canvas.width, this.canvas.height);
    this._setGradientUniforms(prog, g.grad);
    this._bindVao(g, "area", [g.xBuf._fcId, g.yBuf._fcId, g.baseBuf._fcId], () => {
      this._vaoAttr(ATTR_SLOTS.ax0, g.xBuf, 0, 1);
      this._vaoAttr(ATTR_SLOTS.ax1, g.xBuf, 4, 1);
      this._vaoAttr(ATTR_SLOTS.ay0, g.yBuf, 0, 1);
      this._vaoAttr(ATTR_SLOTS.ay1, g.yBuf, 4, 1);
      this._vaoAttr(ATTR_SLOTS.ab0, g.baseBuf, 0, 1);
      this._vaoAttr(ATTR_SLOTS.ab1, g.baseBuf, 4, 1);
    });
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
    gl.uniform4f(u("u_color"), r, gg, b, a * this._fillOpacity(g.trace.style));
    gl.uniform1i(u("u_colorMode"), g.colorMode || 0);
    this._setRectStyleUniforms(prog, g);
    const colorOn = g.colorMode && g.cBuf;
    if (colorOn) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, g.lut);
      gl.uniform1i(u("u_lut"), 0);
    }
    this._bindVao(
      g,
      "rects",
      [g.x0Buf._fcId, g.x1Buf._fcId, g.y0Buf._fcId, g.y1Buf._fcId, colorOn ? g.cBuf._fcId : 0],
      () => {
        this._vaoAttr(ATTR_SLOTS.ax0, g.x0Buf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ax1, g.x1Buf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ay0, g.y0Buf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ay1, g.y1Buf, 0, 1);
        if (colorOn) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 1);
      }
    );
    if (!colorOn) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
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
    gl.uniform4f(u("u_color"), r, gg, b, a * this._fillOpacity(g.trace.style));
    gl.uniform1i(u("u_colorMode"), g.colorMode || 0);
    this._setRectStyleUniforms(prog, g);
    const v0On = g.value0Mode === 1 && g.value0Buf;
    const colorOn = g.colorMode && g.cBuf;
    if (colorOn) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, g.lut);
      gl.uniform1i(u("u_lut"), 0);
    }
    this._bindVao(
      g,
      "bars",
      [
        g.posBuf._fcId, g.value1Buf._fcId,
        v0On ? g.value0Buf._fcId : 0,
        colorOn ? g.cBuf._fcId : 0,
      ],
      () => {
        this._vaoAttr(ATTR_SLOTS.a_pos, g.posBuf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.a_v1, g.value1Buf, 0, 1);
        if (v0On) this._vaoAttr(ATTR_SLOTS.a_v0, g.value0Buf, 0, 1);
        if (colorOn) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 1);
      }
    );
    if (!v0On) gl.vertexAttrib1f(ATTR_SLOTS.a_v0, 0);
    if (!colorOn) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
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

  _axisStyleValue(axis, key) {
    const style = axis && typeof axis.style === "object" ? axis.style : null;
    return style && Object.prototype.hasOwnProperty.call(style, key) ? style[key] : undefined;
  }

  _axisGridDash(axis) {
    const value = String(this._axisStyleValue(axis, "grid_dash") || "solid");
    if (value === "dashed") return [6, 4];
    if (value === "dotted") return [1, 3];
    if (value === "dashdot") return [6, 3, 1, 3];
    return [];
  }

  _axisTickLabelStrategy(axis) {
    const value = String((axis && axis.tick_label_strategy) || "auto").replace(/-/g, "_");
    return ["auto", "hide", "rotate", "stagger", "none", "off"].includes(value) ? value : "auto";
  }

  _axisTickLabelAnchor(axis) {
    const raw = axis && axis.tick_label_anchor !== undefined
      ? axis.tick_label_anchor
      : this._axisStyleValue(axis, "tick_label_anchor");
    if (raw == null) return null;
    const value = String(raw).toLowerCase();
    if (value === "start" || value === "left") return "start";
    if (value === "end" || value === "right") return "end";
    if (value === "center" || value === "middle") return "center";
    return null; // unset/unknown: the caller picks its dimension's default
  }

  _axisTickLabelAngle(axis) {
    const angle = Number(axis ? axis.tick_label_angle : undefined);
    return Number.isFinite(angle) ? angle : null;
  }

  _axisTickLabelMinGap(axis, dim) {
    const gap = Number(axis ? axis.tick_label_min_gap : undefined);
    return Number.isFinite(gap) && gap >= 0 ? gap : (dim === "x" ? 8 : 4);
  }

  _estimateTickLabel(text, fontSize) {
    const s = String(text || "");
    return { w: Math.max(fontSize * 0.7, s.length * fontSize * 0.62), h: fontSize * 1.2 };
  }

  _tickLabelExtent(label, dim, fontSize) {
    const size = this._estimateTickLabel(label.text, fontSize);
    const angle = Math.abs(Number(label.angle || 0)) * Math.PI / 180;
    return dim === "y"
      ? Math.abs(Math.sin(angle)) * size.w + Math.abs(Math.cos(angle)) * size.h
      : Math.abs(Math.cos(angle)) * size.w + Math.abs(Math.sin(angle)) * size.h;
  }

  _tickLabelsCollide(labels, dim, fontSize, minGap, anchor = "center") {
    const rows = new Map();
    for (const label of labels) {
      const row = Number(label.row || 0);
      if (!rows.has(row)) rows.set(row, []);
      rows.get(row).push(label);
    }
    for (const rowLabels of rows.values()) {
      rowLabels.sort((a, b) => a.pos - b.pos);
      if (dim === "x" && anchor !== "center") {
        // Edge-anchored labels all run the same direction from their tick.
        // Rotated ones are parallel lines: they clear each other when the
        // perpendicular gap between adjacent anchors exceeds the line height,
        // regardless of how far their horizontal bounding boxes overlap.
        for (let i = 1; i < rowLabels.length; i++) {
          const prev = rowLabels[i - 1];
          const label = rowLabels[i];
          const spacing = label.pos - prev.pos;
          const angle = Math.abs(Number(label.angle || 0)) * Math.PI / 180;
          if (angle) {
            if (spacing * Math.sin(angle) < fontSize * 1.2 + minGap) return true;
          } else {
            const lead = anchor === "end" ? label : prev;
            if (spacing < this._estimateTickLabel(lead.text, fontSize).w + minGap) return true;
          }
        }
        continue;
      }
      let lastEnd = -Infinity;
      for (const label of rowLabels) {
        const extent = this._tickLabelExtent(label, dim, fontSize);
        const start = label.pos - extent / 2;
        const end = label.pos + extent / 2;
        if (start < lastEnd + minGap) return true;
        lastEnd = end;
      }
    }
    return false;
  }

  _downsampleTickLabels(labels, dim, fontSize, minGap, anchor = "center") {
    if (labels.length <= 1) return labels;
    for (let stride = 2; stride <= labels.length; stride++) {
      const out = labels.filter((_, i) => i % stride === 0);
      if (!this._tickLabelsCollide(out, dim, fontSize, minGap, anchor)) return out;
    }
    return labels.slice(0, 1);
  }

  _layoutTickLabels(axis, dim, labels) {
    const strategyValue = this._axisTickLabelStrategy(axis);
    if (strategyValue === "none" || strategyValue === "off") return [];
    if (labels.length <= 1) {
      const angle = this._axisTickLabelAngle(axis);
      return labels.map((label) => ({ ...label, angle: angle === null ? 0 : angle, row: 0 }));
    }
    const fontSize = Math.max(
      8,
      this._axisStyleNumber(axis, "tick_label_size", this._axisStyleNumber(axis, "tick_size", 11)),
    );
    const minGap = this._axisTickLabelMinGap(axis, dim);
    // y collision keeps the centered extent model: every label on an axis
    // shares one anchor+angle, so an anchored y layout shifts all boxes by
    // the same offset and pairwise gaps are unchanged.
    const anchor = dim === "x" ? (this._axisTickLabelAnchor(axis) ?? "center") : "center";
    const explicitAngle = this._axisTickLabelAngle(axis);
    const baseAngle = explicitAngle === null ? 0 : explicitAngle;
    const withBase = labels.map((label) => ({ ...label, angle: baseAngle, row: 0 }));
    let strategy = strategyValue;
    if (strategy === "auto") {
      if (!this._tickLabelsCollide(withBase, dim, fontSize, minGap, anchor)) return withBase;
      if (dim === "x" && axis.kind === "category" && labels.length <= 16) strategy = "rotate";
      else if (dim === "x" && labels.length <= 24) strategy = "stagger";
      else strategy = "hide";
    }

    let out = withBase;
    if (strategy === "rotate" && dim === "x") {
      const angle = explicitAngle === null ? (axis.side === "top" ? 35 : -35) : explicitAngle;
      out = labels.map((label) => ({ ...label, angle, row: 0 }));
    } else if (strategy === "stagger" && dim === "x") {
      out = labels.map((label, i) => ({ ...label, angle: baseAngle, row: i % 2 }));
    }

    // Strategies handle collisions; a non-colliding label set stays intact
    // even under an explicit "hide" (matches the Python exporters).
    if (this._tickLabelsCollide(out, dim, fontSize, minGap, anchor)) {
      out = this._downsampleTickLabels(out, dim, fontSize, minGap, anchor);
    }
    return out;
  }

  _xTickLabelTransform(axis, angle) {
    const value = Number(angle || 0);
    const side = axis && axis.side === "top" ? "top" : "bottom";
    // An explicit anchor (mpl `ha`) pins that edge as the transform origin,
    // so a rotated label pivots about the point pinned at the tick instead
    // of seesawing its trailing half into the plot. Unset, the anchor is
    // derived from the rotation direction below.
    const anchor = this._axisTickLabelAnchor(axis);
    if (anchor) {
      const shift = anchor === "end" ? "-100%" : anchor === "start" ? "0%" : "-50%";
      const originX = anchor === "end" ? "right" : anchor === "start" ? "left" : "center";
      return {
        transform: `translateX(${shift}) rotate(${value}deg)`,
        origin: `${originX} ${side === "top" ? "bottom" : "top"}`,
      };
    }
    if (value === 0) {
      return {
        transform: "translateX(-50%)",
        origin: side === "top" ? "bottom center" : "top center",
      };
    }
    const anchorAtEnd = (side === "bottom" && value < 0) || (side === "top" && value > 0);
    const verticalOrigin = side === "top" ? "bottom" : "top";
    return {
      transform: `${anchorAtEnd ? "translateX(-100%) " : ""}rotate(${value}deg)`,
      origin: `${verticalOrigin} ${anchorAtEnd ? "right" : "left"}`,
    };
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








  _drawChrome() {
    const s = this.spec;
    const dpr = this.dpr;
    const ctx = this.chrome.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, this.size.w, this.size.h);
    const now = this._now();
    const labelCadenceMs = this._viewAnim ? 80 : 0;
    const updateLabels = labelCadenceMs === 0
      || this._lastLabelDraw === null
      || now - this._lastLabelDraw >= labelCadenceMs;
    if (updateLabels) {
      this.labels.textContent = "";
      this._lastLabelDraw = now;
    }

    const p = this.plot;
    // Plot background (--chart-bg) paints here, at the bottom of the chrome
    // canvas, so the grid and annotation shapes drawn next stay visible and
    // the transparent marks canvas above shows all of it (§36 theming).
    if (this.theme.bg) {
      ctx.fillStyle = cssColor(this.theme.bg);
      ctx.fillRect(p.x, p.y, p.w, p.h);
    }
    const xAxis = this._axis("x");
    const yAxis = this._axis("y");
    const extraXAxes = Object.values(this.axes).filter((axis) =>
      axis && axis.id !== "x" && String(axis.id || "").startsWith("x"));
    const extraYAxes = Object.values(this.axes).filter((axis) =>
      axis && axis.id !== "y" && String(axis.id || "").startsWith("y"));
    const hideX = this._axisTickLabelStrategy(xAxis) === "none";
    const hideY = this._axisTickLabelStrategy(yAxis) === "none";
    const xt = this._axisTicks(
      "x",
      this._axisTickTarget("x", Math.max(3, p.w / (xAxis.kind === "time" ? 90 : 80))),
    );
    const yt = this._axisTicks("y", this._axisTickTarget("y", Math.max(3, p.h / 45)));
    const xEdge = (px) => Math.min(p.x + p.w - 0.5, Math.max(p.x + 0.5, Math.round(px) + 0.5));
    const yEdge = (py) => Math.min(p.y + p.h - 0.5, Math.max(p.y + 0.5, Math.round(py) + 0.5));

    ctx.strokeStyle = this._axisStylePaint(xAxis, "grid_color", this.theme.grid);
    ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(xAxis, "grid_width", 1));
    ctx.globalAlpha = this._axisStyleNumber(xAxis, "grid_opacity", 1);
    ctx.setLineDash(this._axisGridDash(xAxis));
    ctx.beginPath();
    for (const v of (hideX ? [] : xt.ticks)) {
      const px = this._dataPx("x", v);
      if (!Number.isFinite(px)) continue;
      const x = xEdge(px);
      ctx.moveTo(x, p.y);
      ctx.lineTo(x, p.y + p.h);
    }
    ctx.stroke();

    ctx.strokeStyle = this._axisStylePaint(yAxis, "grid_color", this.theme.grid);
    ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(yAxis, "grid_width", 1));
    ctx.globalAlpha = this._axisStyleNumber(yAxis, "grid_opacity", 1);
    ctx.setLineDash(this._axisGridDash(yAxis));
    ctx.beginPath();
    for (const v of (hideY ? [] : yt.ticks)) {
      const py = this._dataPx("y", v);
      if (!Number.isFinite(py)) continue;
      const y = yEdge(py);
      ctx.moveTo(p.x, y);
      ctx.lineTo(p.x + p.w, y);
    }
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.setLineDash([]);

    // Annotation shapes go on the overlay canvas, above the marks canvas —
    // exporter parity: SVG/raster emit annotation marks after the data.
    const octx = this.overlay.getContext("2d");
    octx.setTransform(dpr, 0, 0, dpr, 0, 0);
    octx.clearRect(0, 0, this.size.w, this.size.h);
    this._drawAnnotationShapes(octx);

    // Axis baselines render in the labels overlay — *above* the marks canvas —
    // so a filled mark (bars, area) sits under a crisp, continuous baseline
    // instead of covering the chrome line drawn behind it (grid lines stay on
    // the chrome canvas, behind the data). Rebuilt with the labels; static
    // between throttled zoom frames since the plot rect doesn't move on zoom.
    if (updateLabels) {
      const rule = (styleAxis, left, top, w, h, colorKey = "axis_color") => {
        const d = document.createElement("div");
        d.style.cssText =
          `position:absolute;left:${left}px;top:${top}px;width:${w}px;height:${h}px;` +
          `background:${this._axisStylePaint(styleAxis, colorKey, this.theme.axis)};` +
          "pointer-events:none;";
        this.labels.appendChild(d);
      };
      const frameSides = Array.isArray(s.frame_sides)
        ? s.frame_sides
        : [xAxis.side || "bottom", yAxis.side || "left"];
      if (!hideY) {
        const yWidth = Math.max(1, this._axisStyleNumber(yAxis, "axis_width", 1));
        if (frameSides.includes("left")) rule(yAxis, p.x, p.y, yWidth, p.h);
        if (frameSides.includes("right")) rule(yAxis, p.x + p.w - yWidth, p.y, yWidth, p.h);
      }
      if (!hideX) {
        const xHeight = Math.max(1, this._axisStyleNumber(xAxis, "axis_width", 1));
        if (frameSides.includes("top")) rule(xAxis, p.x, p.y, p.w, xHeight);
        if (frameSides.includes("bottom")) rule(xAxis, p.x, p.y + p.h - xHeight, p.w, xHeight);
      }
      for (const axis of extraXAxes) {
        if (this._axisTickLabelStrategy(axis) === "none") continue;
        const h = Math.max(1, this._axisStyleNumber(axis, "axis_width", 1));
        const y = axis.side === "top" ? p.y : p.y + p.h - h;
        rule(axis, p.x, y, p.w, h);
      }
      for (const axis of extraYAxes) {
        if (this._axisTickLabelStrategy(axis) === "none") continue;
        const w = Math.max(1, this._axisStyleNumber(axis, "axis_width", 1));
        const x = axis.side === "left" ? p.x : p.x + p.w - w;
        rule(axis, x, p.y, w, p.h);
      }

      const tickParts = (axis) => {
        const length = Math.max(0, this._axisStyleNumber(axis, "tick_length", 0));
        const width = Math.max(0.5, this._axisStyleNumber(axis, "tick_width", 1));
        const direction = String(this._axisStyleValue(axis, "tick_direction") || "out");
        if (direction === "in") return { inward: length, outward: 0, width };
        if (direction === "inout") return { inward: length / 2, outward: length / 2, width };
        return { inward: 0, outward: length, width };
      };
      if (!hideX) {
        const tick = tickParts(xAxis);
        const side = xAxis.side || "bottom";
        const edge = side === "top" ? p.y : p.y + p.h;
        for (const value of xt.ticks) {
          const x = this._dataPx("x", value);
          if (!Number.isFinite(x) || x < p.x - 1 || x > p.x + p.w + 1) continue;
          const top = side === "top" ? edge - tick.outward : edge - tick.inward;
          rule(xAxis, x - tick.width / 2, top, tick.width, tick.inward + tick.outward, "tick_color");
        }
      }
      if (!hideY) {
        const tick = tickParts(yAxis);
        const side = yAxis.side || "left";
        const edge = side === "right" ? p.x + p.w : p.x;
        for (const value of yt.ticks) {
          const y = this._dataPx("y", value);
          if (!Number.isFinite(y) || y < p.y - 1 || y > p.y + p.h + 1) continue;
          const left = side === "right" ? edge - tick.inward : edge - tick.outward;
          rule(yAxis, left, y - tick.width / 2, tick.inward + tick.outward, tick.width, "tick_color");
        }
      }
      for (const axis of extraXAxes) {
        if (this._axisTickLabelStrategy(axis) === "none") continue;
        const ticks = this._axisTicks(
          axis.id,
          this._axisTickTarget(axis.id, Math.max(3, p.w / (axis.kind === "time" ? 90 : 80))),
        );
        const tick = tickParts(axis);
        const side = axis.side || "bottom";
        const edge = side === "top" ? p.y : p.y + p.h;
        for (const value of ticks.ticks) {
          const x = this._dataPx(axis.id, value);
          if (!Number.isFinite(x) || x < p.x - 1 || x > p.x + p.w + 1) continue;
          const top = side === "top" ? edge - tick.outward : edge - tick.inward;
          rule(axis, x - tick.width / 2, top, tick.width, tick.inward + tick.outward, "tick_color");
        }
      }
      for (const axis of extraYAxes) {
        if (this._axisTickLabelStrategy(axis) === "none") continue;
        const ticks = this._axisTicks(
          axis.id,
          this._axisTickTarget(axis.id, Math.max(3, p.h / 45)),
        );
        const tick = tickParts(axis);
        const side = axis.side || "right";
        const edge = side === "right" ? p.x + p.w : p.x;
        for (const value of ticks.ticks) {
          const y = this._dataPx(axis.id, value);
          if (!Number.isFinite(y) || y < p.y - 1 || y > p.y + p.h + 1) continue;
          const left = side === "right" ? edge - tick.inward : edge - tick.outward;
          rule(axis, left, y - tick.width / 2, tick.inward + tick.outward, tick.width, "tick_color");
        }
      }
    }

    const label = (text, css, axis, kind = "tick", extraStyle = null) => {
      if (!updateLabels) return;
      const d = document.createElement("div");
      d.textContent = text;
      d.dataset.xyLabelKind = kind;
      d.dataset.xyAxis = axis && axis.id !== undefined ? String(axis.id) : "";
      d.dataset.xyAxisSide = axis && axis.side ? String(axis.side) : "";
      const colorKey = kind === "label"
        ? "label_color"
        : (this._axisStyleValue(axis, "tick_label_color") !== undefined
          ? "tick_label_color" : "tick_color");
      const sizeKey = kind === "label"
        ? "label_size"
        : (this._axisStyleValue(axis, "tick_label_size") !== undefined
          ? "tick_label_size" : "tick_size");
      // Color/size are inline ONLY when the axis spec set them explicitly (the
      // Python set_axis API); otherwise the stylesheet's tick_label/axis_title
      // default applies so a user utility class can win. Structure stays inline.
      let color = "";
      if (this._axisStyleValue(axis, colorKey) !== undefined) {
        color = `color:${this._axisStylePaint(axis, colorKey, this.theme.label)};`;
      }
      let size = "";
      if (this._axisStyleValue(axis, sizeKey) !== undefined) {
        size = `font-size:${Math.max(8, this._axisStyleNumber(axis, sizeKey, 11))}px;`;
      }
      d.style.cssText = `position:absolute;line-height:1.2;white-space:nowrap;${color}${size}${css}`;
      this._applySlot(d, kind === "label" ? "axis_title" : "tick_label");
      this._applyStyle(d, extraStyle);
      this.labels.appendChild(d);
    };
    const xLabelCandidates = [];
    for (const v of (xt.labels || xt.ticks)) {
      const px = this._dataPx("x", v);
      if (px < p.x - 1 || px > p.x + p.w + 1) continue;
      const text = this._axisTickText(xAxis, v, xt.step);
      xLabelCandidates.push({ pos: px, text });
    }
    const tickLabelSize = this._axisStyleNumber(
      xAxis,
      "tick_label_size",
      this._axisStyleNumber(xAxis, "tick_size", 11),
    );
    for (const item of this._layoutTickLabels(xAxis, "x", xLabelCandidates)) {
      const rowOffset = Number(item.row || 0) * (Math.max(8, tickLabelSize) + 4);
      const top = xAxis.side === "top" ? p.y - 18 - rowOffset : p.y + p.h + 6 + rowOffset;
      const placement = this._xTickLabelTransform(xAxis, item.angle);
      label(
        item.text,
        `left:${item.pos}px;top:${top}px;transform:${placement.transform};` +
          `transform-origin:${placement.origin};`,
        xAxis,
      );
    }
    for (const axis of extraXAxes) {
      const ticks = this._axisTicks(
        axis.id,
        this._axisTickTarget(axis.id, Math.max(3, p.w / (axis.kind === "time" ? 90 : 80))),
      );
      const labelCandidates = [];
      for (const value of (ticks.labels || ticks.ticks)) {
        const px = this._dataPx(axis.id, value);
        if (px < p.x - 1 || px > p.x + p.w + 1) continue;
        labelCandidates.push({ pos: px, text: this._axisTickText(axis, value, ticks.step) });
      }
      for (const item of this._layoutTickLabels(axis, "x", labelCandidates)) {
        const tickLabelSize = this._axisStyleNumber(
          axis,
          "tick_label_size",
          this._axisStyleNumber(axis, "tick_size", 11),
        );
        const rowOffset = Number(item.row || 0) * (Math.max(8, tickLabelSize) + 4);
        const top = axis.side === "top" ? p.y - 18 - rowOffset : p.y + p.h + 6 + rowOffset;
        const placement = this._xTickLabelTransform(axis, item.angle);
        label(
          item.text,
          `left:${item.pos}px;top:${top}px;transform:${placement.transform};` +
            `transform-origin:${placement.origin};`,
          axis,
        );
      }
      if (axis.label && this._axisTickLabelStrategy(axis) !== "none") {
        const top = axis.side === "top" ? p.y - 34 : p.y + p.h + 24;
        const fallbackCss =
          `left:${p.x + p.w / 2}px;top:${top}px;transform:translateX(-50%);font-weight:500;`;
        const placement = this._axisLabelCss(axis, "x", fallbackCss);
        label(axis.label, placement.css, axis, "label", placement.style);
      }
    }
    const yLabelCandidates = [];
    for (const v of (yt.labels || yt.ticks)) {
      const py = this._dataPx("y", v);
      if (py < p.y - 1 || py > p.y + p.h + 1) continue;
      const text = this._axisTickText(yAxis, v, yt.step);
      yLabelCandidates.push({ pos: py, text });
    }
    // Same anchored-pivot scheme as the x labels above: the pinned edge is
    // the transform origin, so a rotated label pivots about the point at the
    // tick. Unset defaults to the tick-side edge — mpl `ha`: "end" left of
    // the plot, "start" right of it — reproducing the classic layout.
    const yLabelCss = (axis, onRight, item) => {
      const pin = onRight ? p.x + p.w + 8 : p.x - 8;
      const anchor = this._axisTickLabelAnchor(axis) ?? (onRight ? "start" : "end");
      const shift = anchor === "end" ? "-100%" : anchor === "start" ? "0%" : "-50%";
      const originX = anchor === "end" ? "right" : anchor === "start" ? "left" : "center";
      return `left:${pin}px;top:${item.pos}px;` +
        `transform:translate(${shift},-50%) rotate(${Number(item.angle || 0)}deg);` +
        `transform-origin:${originX} center;`;
    };
    for (const item of this._layoutTickLabels(yAxis, "y", yLabelCandidates)) {
      label(item.text, yLabelCss(yAxis, yAxis.side === "right", item), yAxis);
    }
    for (const axis of extraYAxes) {
      const ticks = this._axisTicks(axis.id, this._axisTickTarget(axis.id, Math.max(3, p.h / 45)));
      const labelCandidates = [];
      for (const v of (ticks.labels || ticks.ticks)) {
        const py = this._dataPx(axis.id, v);
        if (py < p.y - 1 || py > p.y + p.h + 1) continue;
        const text = this._axisTickText(axis, v, ticks.step);
        labelCandidates.push({ pos: py, text });
      }
      for (const item of this._layoutTickLabels(axis, "y", labelCandidates)) {
        label(item.text, yLabelCss(axis, axis.side !== "left", item), axis);
      }
      if (axis.label && this._axisTickLabelStrategy(axis) !== "none") {
        const fallbackCss = axis.side === "left"
          ? `left:10px;top:${p.y + p.h / 2}px;transform:rotate(-90deg) translateX(50%);transform-origin:left;font-weight:500;`
          : `left:${p.x + p.w + 40}px;top:${p.y + p.h / 2}px;transform:rotate(90deg) translateX(-50%);transform-origin:left;font-weight:500;`;
        const placement = this._axisLabelCss(axis, "y", fallbackCss);
        label(axis.label, placement.css, axis, "label", placement.style);
      }
    }
    if (s.x_axis.label && !hideX) {
      const top = xAxis.side === "top" ? p.y - 34 : p.y + p.h + 24;
      const fallbackCss = `left:${p.x + p.w / 2}px;top:${top}px;transform:translateX(-50%);font-weight:500;`;
      const placement = this._axisLabelCss(xAxis, "x", fallbackCss);
      label(s.x_axis.label, placement.css, xAxis, "label", placement.style);
    }
    if (s.y_axis.label && !hideY) {
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
    // Global pick-id space: trace ranges are [pickBase, pickBase + n), bases
    // start at 1 so the all-zero clear stays the background sentinel.
    let base = 1;
    for (const g of this.gpuTraces) {
      // Density traces pick only while drilled to points (§5); the drill
      // sibling carries the buffers, the host g keeps the range → trace id.
      const pg = g.tier === "density"
        ? (g.drill && !g._drillDying && this._viewInside(g.drill.win) ? g.drill : null)
        : (markOf(g.trace.kind).pointPick ? g : null);
      if (!pg || !pg.n || base + pg.n > 0x7fffffff) {
        // Stale ranges must not alias; the 2^31-1 guard degrades gracefully
        // (trace unpickable) if the global id space is ever exhausted.
        g.pickBase = -1;
        g.pickCount = 0;
        continue;
      }
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
      gl.uniform1i(u("u_pick_base"), base);
      g.pickBase = base;
      g.pickCount = pg.n;
      const sizeOn = pg.sizeMode === 1 && pg.sBuf;
      this._bindVao(
        pg,
        "pick",
        [pg.xBuf._fcId, pg.yBuf._fcId, sizeOn ? pg.sBuf._fcId : 0],
        () => {
          this._vaoAttr(ATTR_SLOTS.ax, pg.xBuf, 0, 0);
          this._vaoAttr(ATTR_SLOTS.ay, pg.yBuf, 0, 0);
          if (sizeOn) this._vaoAttr(ATTR_SLOTS.a_sval, pg.sBuf, 0, 0);
        }
      );
      if (!sizeOn) gl.vertexAttrib1f(ATTR_SLOTS.a_sval, 0.5);
      gl.drawArrays(gl.POINTS, 0, pg.n);
      base += pg.n;
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
    // Reassemble the global 32-bit id; zero is the background sentinel.
    const id = buf[0] + buf[1] * 0x100 + buf[2] * 0x10000 + buf[3] * 0x1000000;
    if (id === 0) return null;
    const g = this.gpuTraces.find(
      (t) => t.pickBase > 0 && id >= t.pickBase && id < t.pickBase + t.pickCount
    );
    if (!g) return null;
    return { trace: g.trace.id, index: id - g.pickBase, g };
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
    // Mirror _drawHeatmap's display-orientation anchoring: on a reversed axis
    // buffer row/column 0 sits at the opposite end of the data range.
    const [ax0, ax1] = this._axisRange(g.xAxis) ?? [this.view.x0, this.view.x1];
    const [ay0, ay1] = this._axisRange(g.yAxis) ?? [this.view.y0, this.view.y1];
    const fx = ((ax0 ?? this.view.x0) > (ax1 ?? this.view.x1)) ? (x1 - dataX) : (dataX - x0);
    const fy = ((ay0 ?? this.view.y0) > (ay1 ?? this.view.y1)) ? (y1 - dataY) : (dataY - y0);
    const col = Math.min(h.w - 1, Math.max(0, Math.floor((fx / (x1 - x0)) * h.w)));
    const row = Math.min(h.h - 1, Math.max(0, Math.floor((fy / (y1 - y0)) * h.h)));
    return { trace: g.trace.id, index: row * h.w + col, g, heatmap: { row, col }, synthetic: true };
  }












  // -- interaction ----------------------------------------------------------










  // -- modebar & zoom (Plotly-parity controls) ------------------------------












  // Repaint the visible canvas without invalidating the pick framebuffer —
  // the hover-highlight caller's entry point (mechanics in draw()). Without
  // this, every hover-target change re-rendered all N points into the pick
  // buffer on the next pointermove — the dominant steady-hover cost at large
  // N (§17).
  _drawKeepPick() {
    this.draw(true);
  }

  _hover(e) {
    // Pointer exploration supersedes any positional prefix retained for
    // keyboard readouts and their asynchronous exact-value replies.
    this._a11yKeyboardReadout = null;
    if (this._transitionActive()) {
      const hadHover = this._hoverId !== -1;
      this._hoverId = -1;
      this._hoverTarget = null;
      this._lastHoverXY = null;
      this._pickSeq = (this._pickSeq || 0) + 1;
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
      this._lastHoverXY = null;
      this._pickSeq = (this._pickSeq || 0) + 1;
      this.tooltip.style.display = "none";
      if (hadHover) this._drawKeepPick();
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
    this._drawKeepPick();
  }




  // -- Tier-2 drill-in (§5: tier follows the *visible* count) ---------------





  _asF32(b) {
    if (b instanceof ArrayBuffer) return new Float32Array(b);
    if (b.byteOffset % 4 === 0) {
      return new Float32Array(b.buffer, b.byteOffset, Math.floor(b.byteLength / 4));
    }
    return new Float32Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
  }

  _asU8(b) {
    if (b instanceof ArrayBuffer) return new Uint8Array(b);
    return new Uint8Array(b.buffer, b.byteOffset, b.byteLength);
  }

  _asU32(b) {
    if (b instanceof ArrayBuffer) return new Uint32Array(b);
    if (b.byteOffset % 4 === 0) {
      return new Uint32Array(b.buffer, b.byteOffset, Math.floor(b.byteLength / 4));
    }
    return new Uint32Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
  }

  _applyTheme() {
    this.theme = readTheme(this.root);
    // A theme read on a detached root saw no computed styles; stay flagged
    // stale until the element connects and _healStaleTheme re-reads.
    this._themeStale = !this.root.isConnected;
    for (const g of this.gpuTraces) {
      // Re-resolve CSS-expressed constant colors (§36 live re-resolution);
      // each mark kind knows where its constant color lives in the spec.
      markOf(g.trace.kind).refreshColor?.(this, g);
    }
  }

  refreshTheme() {
    if (this._destroyed) return;
    this._applyTheme();
    this.draw();
  }

  // Once a stale-themed root is connected, re-read tokens and re-resolve mark
  // colors in place. Returns true when a heal happened (callers outside a
  // frame should redraw).
  _healStaleTheme() {
    if (!this._themeStale || !this.root.isConnected) return false;
    this._applyTheme();
    return true;
  }

  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;
    XY_CONTEXT_GOVERNOR.unregister(this);
    this._ctxIo?.disconnect();
    this._ctxIo = null;
    clearTimeout(this._rebinTimer);
    if (this._rebinWorker) {
      this._rebinWorker.terminate();
      if (this._rebinWorker._fcUrl) URL.revokeObjectURL(this._rebinWorker._fcUrl);
      this._rebinWorker = null;
    }
    this._ro?.disconnect();
    this._io?.disconnect();
    this._io = null;
    this._themeWatch?.removeEventListener?.("change", this._onScheme);
    this._themeMutationObserver?.disconnect();
    this._themeMutationObserver = null;
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
    this._destroyDensitySample(g);
    this._deleteVaos(g);
    this._deleteVaos(g.drill);
    this._deleteBuffers(g, [
      "xBuf", "yBuf", "cBuf", "sBuf", "selBuf", "baseBuf",
      "x0Buf", "x1Buf", "x2Buf", "y0Buf", "y1Buf", "y2Buf",
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
    if (this.quadVao) gl.deleteVertexArray(this.quadVao);
    this.quadVao = null;
    for (const p of this._progCache ? this._progCache.values() : []) {
      if (p) gl.deleteProgram(p);
    }
    if (this._progCache) this._progCache.clear();
    this._glPrograms = this._progCache;
    this.gpuTraces = [];
  }
}
