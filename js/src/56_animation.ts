import { PROTOCOL } from "./00_header";
import { ChartView } from "./50_chartview";
import type { ChartSpec, ColumnMeta, GpuTrace, PayloadBuffers, TraceSpec } from "./05_types";

// Declarative data animation: one browser clock, bounded previous/next GPU
// state, no Python round-trips per frame. Full scene refreshes call
// updatePayload(); rapid updates cancel/coalesce latest-wins.

const XY_EASINGS: Record<string, number[]> = {
  linear: [0, 0, 1, 1],
  ease: [0.25, 0.1, 0.25, 1],
  "ease-in": [0.42, 0, 1, 1],
  "ease-out": [0, 0, 0.58, 1],
  "ease-in-out": [0.42, 0, 0.58, 1],
};

/** `easing: {type: "spring", ...}` — a duration-independent spring policy. */
interface SpringEasing {
  type?: string;
  stiffness?: number;
  damping?: number;
  mass?: number;
}

/** `easing`: a named curve, four explicit bezier control points, or a spring. */
type Easing = string | number[] | SpringEasing;

/** The figure-level `animation` block merged with a trace's own override, as
 * `_resolvedAnimation` returns it. Open like the rest of the wire: the kernel
 * may ship keys this client ignores. */
interface AnimationConfig {
  _present?: boolean;
  enabled?: boolean;
  enter?: string;
  update?: string;
  easing?: Easing;
  delay?: number;
  duration?: number;
  match?: string;
  interpolate?: string[];
  [key: string]: any;
}

/** One trace's in-flight transition, resolved once at the start of a run. */
interface AnimationRecord {
  g: GpuTrace;
  config: AnimationConfig;
  phase: string;
  delay: number;
  duration: number;
}

/** Old→new index pairing for one trace (`g._transitionMatch`). `fallback`
 * records the §28 reason whenever the requested strategy was not honored. */
interface TransitionMatch {
  strategy: string;
  pairs: [number, number][];
  fallback: string | null;
}

/** The CPU-side bar cache (`g._cpuBar`) bar interpolation reads back. */
interface BarCpu {
  pos: Float32Array;
  value1: Float32Array;
  value0: Float32Array | null;
  value0Const?: number;
  posMeta: ColumnMeta;
  value1Meta: ColumnMeta;
  value0Meta: ColumnMeta | null;
  width: number;
  [key: string]: any;
}

function xyCubicBezierProgress(value: number, points: number[]) {
  const x1 = Number(points[0]), y1 = Number(points[1]);
  const x2 = Number(points[2]), y2 = Number(points[3]);
  const sample = (t: number, a: number, b: number) => {
    const u = 1 - t;
    return 3 * u * u * t * a + 3 * u * t * t * b + t * t * t;
  };
  const slope = (t: number, a: number, b: number) => {
    const u = 1 - t;
    return 3 * u * u * a + 6 * u * t * (b - a) + 3 * t * t * (1 - b);
  };
  let t = value;
  for (let i = 0; i < 5; i++) {
    const d = slope(t, x1, x2);
    if (Math.abs(d) < 1e-6) break;
    t = Math.max(0, Math.min(1, t - (sample(t, x1, x2) - value) / d));
  }
  let lo = 0, hi = 1;
  for (let i = 0; i < 8; i++) {
    if (sample(t, x1, x2) < value) lo = t; else hi = t;
    t = (lo + hi) * 0.5;
  }
  return sample(t, y1, y2);
}

function xySpringProgress(value: number, policy: SpringEasing) {
  const stiffness = Math.max(1e-6, Number(policy.stiffness) || 170);
  const damping = Math.max(1e-6, Number(policy.damping) || 26);
  const mass = Math.max(1e-6, Number(policy.mass) || 1);
  const w0 = Math.sqrt(stiffness / mass);
  const zeta = damping / (2 * Math.sqrt(stiffness * mass));
  // Six natural periods gives a duration-independent spring. Normalize the
  // sampled response by its value at the endpoint so progress reaches 1
  // continuously instead of snapping from a nearly-settled value on the last
  // frame.
  const response = (progress: number) => {
    const time = progress * 6 / w0;
    if (zeta < 1) {
      const wd = w0 * Math.sqrt(1 - zeta * zeta);
      return 1 - Math.exp(-zeta * w0 * time) *
        (Math.cos(wd * time) + (zeta * w0 / wd) * Math.sin(wd * time));
    }
    return 1 - Math.exp(-w0 * time) * (1 + w0 * time);
  };
  const endpoint = response(1);
  const result = Math.abs(endpoint) > 1e-9 ? response(value) / endpoint : value;
  return Math.max(0, Math.min(1.15, result));
}

function xyAnimationEase(value: number, easing: Easing) {
  if (easing && typeof easing === "object" && !Array.isArray(easing) && easing.type === "spring") {
    return xySpringProgress(value, easing);
  }
  const points = Array.isArray(easing) ? easing : XY_EASINGS[easing as string] || XY_EASINGS["ease-out"];
  return xyCubicBezierProgress(value, points);
}

Object.assign(ChartView.prototype, {
  _resolvedAnimation(trace: TraceSpec): AnimationConfig {
    return {
      ...(this.spec.animation || {}),
      ...((trace && trace.animation) || {}),
      _present: !!this.spec.animation || !!(trace && trace.animation),
    };
  },

  _animationEnabled(config: AnimationConfig) {
    if (!config._present) return false;
    if (config.enabled === false) return false;
    if (config.enabled === true) return true; // explicit opt-in overrides reduced motion
    return !this._prefersReducedMotion();
  },

  _defaultEntrance(kind: string) {
    if (kind === "line" || kind === "area" || kind === "error_band") return "reveal";
    if (kind === "bar" || kind === "column") return "grow";
    if (kind === "scatter" || kind === "errorbar") return "scale";
    return "none";
  },

  _setTransitionVisual(g: GpuTrace, phase: string, progress: number, config: AnimationConfig) {
    const p = Math.max(0, Math.min(1, progress));
    g._transitionOpacity = 1;
    g._transitionScale = 1;
    g._transitionReveal = 1;
    g._transitionGrow = 1;
    if (phase === "exit") {
      // Removed items drop immediately rather than fading the retained old
      // trace; XY never cross-fades during data animation.
      g._transitionOpacity = 0;
      return;
    }
    if (phase === "update") {
      // The old trace is suppressed for every update. Supported direct
      // layouts interpolate geometry; unsupported layouts snap without an
      // opacity blend (no cross-fade).
      g._transitionPositionProgress = p;
      return;
    }
    let enter = config.enter || "auto";
    if (enter === "auto") enter = this._defaultEntrance(g.trace.kind);
    if (enter === "none") return;
    if (enter === "scale") {
      if (g.trace.kind === "scatter") g._transitionScale = p;
      else if (g.trace.kind === "errorbar") g._transitionScale = p;
      else if (g.trace.kind === "bar" || g.trace.kind === "column") g._transitionGrow = p;
      else if (g.trace.kind === "line" || g.trace.kind === "area" ||
               g.trace.kind === "error_band") g._transitionReveal = p;
    }
    if (enter === "reveal") g._transitionReveal = p;
    if (enter === "grow") g._transitionGrow = p;
  },

  _clearTransitionVisual(g: GpuTrace) {
    delete g._transitionOpacity;
    delete g._transitionScale;
    delete g._transitionReveal;
    delete g._transitionGrow;
    delete g._transitionPositionProgress;
    delete g._transitionPhase;
    delete g._transitionPrevXValues;
    delete g._transitionPrevYValues;
    delete g._transitionPrevPosValues;
    delete g._transitionPrevValue1Values;
    delete g._transitionPrevValue0Values;
    delete g._transitionPrevWidth;
    delete g._transitionPositionInterpolated;
    this._deleteBuffers(g, [
      "_transitionPrevXBuf", "_transitionPrevYBuf",
      "_transitionPrevPosBuf", "_transitionPrevValue1Buf", "_transitionPrevValue0Buf",
    ]);
  },

  _emitAnimationLifecycle(stage: string, phase: string, extra: Record<string, any> = {}) {
    const detail = { stage, phase, ...extra, view: this._eventView(`animation_${stage}`) };
    this._dispatchChartEvent(`animation_${stage}`, detail);
    this.comm?.send?.({ type: `animation_${stage}`, phase, ...extra });
  },

  _runDataAnimation(phase: string, current: GpuTrace[], exiting: GpuTrace[] = []) {
    if (this._dataAnimRaf) cancelAnimationFrame(this._dataAnimRaf);
    const epoch = (this._dataAnimEpoch || 0) + 1;
    this._dataAnimEpoch = epoch;
    const records: AnimationRecord[] = [];
    for (const g of current) {
      const config = this._resolvedAnimation(g.trace);
      const recordPhase = g._transitionPhase || phase;
      if (!this._animationEnabled(config) ||
          (recordPhase === "enter" && config.enter === "none") ||
          (recordPhase === "update" && config.update === "none")) {
        this._clearTransitionVisual(g);
        continue;
      }
      records.push({ g, config, phase: recordPhase, delay: Number(config.delay) || 0, duration: Math.max(0, Number(config.duration) || 0) });
    }
    for (const g of exiting) {
      g._transitionOpacity = 0;
    }
    if (!records.length) {
      for (const g of current) this._clearTransitionVisual(g);
      if (this._transitionView) {
        this.view = { ...this._transitionView.to };
        this._transitionView = null;
      }
      this._destroyTransitionOldTraces();
      this.draw();
      return false;
    }
    const start = this._now();
    this._dataAnim = { epoch, phase, start };
    this._emitAnimationLifecycle("start", phase);
    const tick = () => {
      if (this._destroyed || !this._dataAnim || this._dataAnim.epoch !== epoch) return;
      const now = this._now();
      let active = false;
      let maxRaw = 0;
      for (const record of records) {
        const raw = record.duration <= 0
          ? (now >= start + record.delay ? 1 : 0)
          : Math.max(0, Math.min(1, (now - start - record.delay) / record.duration));
        if (this._transitionView) maxRaw = Math.max(maxRaw, raw);
        const eased = xyAnimationEase(raw, record.config.easing);
        this._setTransitionVisual(record.g, record.phase, eased, record.config);
        if (raw < 1) active = true;
      }
      if (this._transitionView) {
        const p = xyAnimationEase(maxRaw, (this.spec.animation || {}).easing);
        const from = this._transitionView.from, to = this._transitionView.to;
        this.view = {
          x0: from.x0 + (to.x0 - from.x0) * p,
          x1: from.x1 + (to.x1 - from.x1) * p,
          y0: from.y0 + (to.y0 - from.y0) * p,
          y1: from.y1 + (to.y1 - from.y1) * p,
        };
      }
      this.draw();
      if (active) {
        this._dataAnimRaf = requestAnimationFrame(tick);
      } else {
        this._dataAnimRaf = null;
        for (const record of records) this._clearTransitionVisual(record.g);
        this._finishDataAnimation(phase);
      }
    };
    this._dataAnimRaf = requestAnimationFrame(tick);
    return true;
  },

  _finishDataAnimation(phase: string) {
    this._dataAnim = null;
    if (this._transitionView) {
      this.view = { ...this._transitionView.to };
      this._transitionView = null;
    }
    this._destroyTransitionOldTraces();
    this._emitAnimationLifecycle("end", phase);
  },

  _startEntranceAnimation() {
    const capture = Number(this.spec.animation_capture_progress);
    if (Number.isFinite(capture) && capture >= 0 && capture <= 1) {
      for (const g of this.gpuTraces || []) {
        const config = this._resolvedAnimation(g.trace);
        if (config._present && config.enabled !== false && config.enter !== "none") {
          this._setTransitionVisual(g, "enter", xyAnimationEase(capture, config.easing), config);
        } else {
          this._clearTransitionVisual(g);
        }
      }
      this.draw();
      return;
    }
    this._runDataAnimation("enter", this.gpuTraces || []);
  },

  _destroyTransitionOldTraces() {
    if (!this._transitionOldTraces || !this.gl) {
      this._transitionOldTraces = null;
      return;
    }
    const seen = new Set();
    for (const g of this._transitionOldTraces) this._destroyTraceResources(g, seen);
    this._transitionOldTraces = null;
  },

  _transitionMatches(previous: GpuTrace, next: GpuTrace, config: AnimationConfig): TransitionMatch {
    let strategy = config.match || "index";
    const pairs: [number, number][] = [];
    let fallback = next.trace.animation_fallback || null;
    if ((previous.n || 0) > 200000 || (next.n || 0) > 200000) {
      return {
        strategy: "snap",
        pairs,
        fallback: fallback || `snap:${strategy}-match-limit`,
      };
    }
    if (strategy === "key") {
      if (previous._transitionKeyIndex && next._transitionKeys) {
        for (let ni = 0; ni < next._transitionKeys.length; ni++) {
          const oi = previous._transitionKeyIndex.get(next._transitionKeys[ni]);
          if (oi !== undefined) pairs.push([oi, ni]);
        }
      } else {
        fallback ||= "index:missing-keys";
        strategy = "index";
      }
    }
    if (strategy === "append") {
      const oldX = previous._cpu && previous._cpu.x;
      const newX = next._cpu && next._cpu.x;
      if (oldX && newX && oldX.length <= 200000 && newX.length <= 200000) {
        const index = new Map();
        for (let i = 0; i < oldX.length; i++) {
          const value = this._decodeValue(oldX, previous.xMeta, i);
          if (Number.isFinite(value)) index.set(value.toPrecision(12), i);
        }
        for (let i = 0; i < newX.length; i++) {
          const value = this._decodeValue(newX, next.xMeta, i);
          const oi = Number.isFinite(value) ? index.get(value.toPrecision(12)) : undefined;
          if (oi !== undefined) pairs.push([oi, i]);
        }
      } else {
        fallback ||= "index:append-limit";
        strategy = "index";
      }
    }
    if (strategy === "index") {
      const count = Math.min(previous.n || 0, next.n || 0);
      for (let i = 0; i < count; i++) pairs.push([i, i]);
    }
    return {
      strategy,
      pairs,
      fallback,
    };
  },

  _recordAnimationFallback(trace: TraceSpec, fallback: string | null) {
    if (!trace || !fallback) return;
    trace.animation_fallback = fallback;
    if (this.root && this.root.dataset) {
      this.root.dataset.xyAnimationFallback = fallback;
    }
  },

  _preparePositionInterpolation(previous: GpuTrace, next: GpuTrace, config: AnimationConfig) {
    const match = next._transitionMatch;
    const policies = config.interpolate || [];
    if (config.update !== "interpolate" || !policies.includes("position") || !match) return false;
    if (["bar", "column"].includes(next.trace.kind)) {
      return this._prepareBarPositionInterpolation(previous, next, match);
    }
    if (!["scatter", "line"].includes(next.trace.kind)) return false;
    if (!previous._cpu || !next._cpu || next.n !== next._cpu.x.length ||
        previous.n !== previous._cpu.x.length) {
      match.fallback ||= "snap:layout-mismatch";
      return false;
    }
    const startX = new Float32Array(next._cpu.x);
    const startY = new Float32Array(next._cpu.y);
    const encode = (value: number, meta: ColumnMeta) => (value - (Number(meta.offset) || 0)) * (Number(meta.scale) || 1);
    const displayedValue = (axis: string, index: number) => {
      const cpu = previous._cpu[axis];
      const starts = previous[axis === "x" ? "_transitionPrevXValues" : "_transitionPrevYValues"];
      const progress = previous._transitionPositionProgress;
      if (!starts || !Number.isFinite(progress)) {
        return this._decodeValue(cpu, previous[`${axis}Meta`], index);
      }
      const encoded = starts[index] + (cpu[index] - starts[index]) * progress;
      const meta = previous[`${axis}Meta`];
      return encoded / (meta.scale || 1) + meta.offset;
    };
    for (const [oldIndex, newIndex] of match.pairs) {
      const x = displayedValue("x", oldIndex);
      const y = displayedValue("y", oldIndex);
      if (Number.isFinite(x) && Number.isFinite(y)) {
        startX[newIndex] = encode(x, next.xMeta);
        startY[newIndex] = encode(y, next.yMeta);
      }
    }
    next._transitionPrevXBuf = this._upload(startX);
    next._transitionPrevYBuf = this._upload(startY);
    next._transitionPrevXValues = startX;
    next._transitionPrevYValues = startY;
    next._transitionPositionProgress = 0;
    next._transitionPositionInterpolated = true;
    previous._transitionSkipExit = true;
    return true;
  },

  _prepareBarPositionInterpolation(previous: GpuTrace, next: GpuTrace, match: TransitionMatch) {
    const oldBar: BarCpu = previous._cpuBar;
    const newBar: BarCpu = next._cpuBar;
    if (!oldBar || !newBar || previous.orientation !== next.orientation ||
        next.n !== newBar.pos.length || previous.n !== oldBar.pos.length) {
      match.fallback ||= "snap:layout-mismatch";
      return false;
    }
    const startPos = new Float32Array(newBar.pos);
    const startValue1 = new Float32Array(newBar.value1);
    const startValue0 = new Float32Array(next.n);
    const encode = (value: number, meta: ColumnMeta) => (value - (Number(meta.offset) || 0)) * (Number(meta.scale) || 1);
    const decode = (value: number, meta: ColumnMeta) => value / (Number(meta.scale) || 1) + (Number(meta.offset) || 0);
    const value0At = (bar: BarCpu, index: number) => bar.value0
      ? decode(bar.value0[index], bar.value0Meta)
      : Number(bar.value0Const) || 0;
    const displayed = (values: Float32Array, current: Float32Array, meta: ColumnMeta, index: number) => {
      const progress = previous._transitionPositionProgress;
      if (!values || !Number.isFinite(progress)) return decode(current[index], meta);
      return decode(values[index] + (current[index] - values[index]) * progress, meta);
    };
    const displayedValue0 = (index: number) => {
      const starts = previous._transitionPrevValue0Values;
      const progress = previous._transitionPositionProgress;
      const current = value0At(oldBar, index);
      if (!starts || !Number.isFinite(progress)) return current;
      const start = decode(starts[index], oldBar.value1Meta);
      return start + (current - start) * progress;
    };
    for (let i = 0; i < next.n; i++) {
      startValue0[i] = encode(value0At(newBar, i), newBar.value1Meta);
    }
    for (const [oldIndex, newIndex] of match.pairs) {
      const pos = displayed(
        previous._transitionPrevPosValues,
        oldBar.pos,
        oldBar.posMeta,
        oldIndex
      );
      const value1 = displayed(
        previous._transitionPrevValue1Values,
        oldBar.value1,
        oldBar.value1Meta,
        oldIndex
      );
      const value0 = displayedValue0(oldIndex);
      if (Number.isFinite(pos) && Number.isFinite(value0) && Number.isFinite(value1)) {
        startPos[newIndex] = encode(pos, newBar.posMeta);
        startValue1[newIndex] = encode(value1, newBar.value1Meta);
        startValue0[newIndex] = encode(value0, newBar.value1Meta);
      }
    }
    const progress = previous._transitionPositionProgress;
    const previousWidth = Number.isFinite(previous._transitionPrevWidth) && Number.isFinite(progress)
      ? previous._transitionPrevWidth + (oldBar.width - previous._transitionPrevWidth) * progress
      : oldBar.width;
    next._transitionPrevPosBuf = this._upload(startPos);
    next._transitionPrevValue1Buf = this._upload(startValue1);
    next._transitionPrevValue0Buf = this._upload(startValue0);
    next._transitionPrevPosValues = startPos;
    next._transitionPrevValue1Values = startValue1;
    next._transitionPrevValue0Values = startValue0;
    next._transitionPrevWidth = previousWidth;
    next._transitionPositionProgress = 0;
    next._transitionPositionInterpolated = true;
    previous._transitionSkipExit = true;
    return true;
  },

  updatePayload(spec: ChartSpec, buffer: PayloadBuffers) {
    if (this._destroyed || !spec || spec.protocol !== PROTOCOL) return false;
    if (this._dataAnimRaf) cancelAnimationFrame(this._dataAnimRaf);
    this._dataAnimRaf = null;
    if (this._dataAnim) {
      this._emitAnimationLifecycle("end", this._dataAnim.phase, { cancelled: true });
    }
    this._dataAnim = null;
    // Latest wins: drop the older retained endpoint before retaining the
    // currently displayed scene, so at most previous+next GPU state exists.
    this._destroyTransitionOldTraces();
    const previous = this.gpuTraces || [];
    const fromView = { ...this.view };
    this.spec = spec;
    this.interaction = spec.interaction || {};
    this.markStyle = spec.mark_style || {};
    this.axes = this._normalizeAxes(spec);
    this._payload = buffer;
    // A full payload re-homes the view to its own axis ranges (reflex-integration
    // §4 "state-driven rebuild"): unlike streaming append, it carries no
    // follow-policy, so it behaves like a fresh mount of the new data. Clear the
    // prior home before clamping so `_clampView` derives extents from the
    // incoming spec instead of capping the window to the previous home span —
    // otherwise a recomputed figure whose data range *grew* (e.g. the §4 detail
    // histogram gaining points, and thus a taller count axis, as its linked
    // overview zooms out) would be pinned to the old, smaller magnification and
    // paint as a solid clipped block. Mirrors the constructor's home setup.
    this.view0 = undefined;
    this.view0 = this._clampView({
      ranges: Object.fromEntries(
        Object.entries(this.axes).map(([id, axis]: any) => [id, [...axis.range]]),
      ),
    });
    const target = { ...this.view0 };
    if (this._glLost || !this.gl) {
      this.view = { ...target };
      return true;
    }
    this.gpuTraces = spec.traces.map((trace) => this._buildTrace(buffer, trace));
    for (const next of this.gpuTraces) {
      const old = previous.find((candidate: GpuTrace) => candidate.trace.id === next.trace.id && candidate.trace.kind === next.trace.kind);
      if (old) {
        const config = this._resolvedAnimation(next.trace);
        old._transitionExitTrace = next.trace;
        if (this._animationEnabled(config) && config.update !== "none") {
          next._transitionMatch = this._transitionMatches(old, next, config);
          this._preparePositionInterpolation(old, next, config);
          old._transitionSkipExit = true;
          this._recordAnimationFallback(next.trace, next._transitionMatch.fallback);
        }
      } else {
        next._transitionPhase = "enter";
      }
    }
    this._transitionOldTraces = previous;
    const animateDomain = this.gpuTraces.some((g: GpuTrace) => {
      const config = this._resolvedAnimation(g.trace);
      return this._animationEnabled(config) && config.update === "interpolate" &&
        (config.interpolate || []).includes("domain");
    });
    this._transitionView = animateDomain ? { from: fromView, to: target } : null;
    if (!animateDomain) this.view = { ...target };
    this._updatePickable();
    if (!this._runDataAnimation("update", this.gpuTraces, previous)) {
      this.view = { ...target };
      this._transitionView = null;
    }
    return true;
  },
} as ThisType<ChartView> & Record<string, unknown>);
