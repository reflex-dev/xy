import { FUNNEL_SLOTS, PROTOCOL, TRACE_GPU_BUFFERS, xyByteSpan } from "./00_header";
import { buildLutData, colormapKey, colormapStops } from "./10_colormaps";
import { chartBackdrop, cssColor, ensureChromeStylesheet, hexColor, parseColor, readTheme, safeCssPaint } from "./20_theme";
import { angularTicks, categoryTicks, fmtAxis, fmtGeneral, fmtLinear, fmtLog, fmtValue, linearTicks, logTicks, timeTicks } from "./30_ticks";
import { AREA_FS, AREA_VS, ATTR_SLOTS, BAR_VS, DENSITY_FS, FUNNEL_VS, GRID_VS, HEATMAP_FS, LINE_CAP_MODES, LINE_FS, LINE_VS, MESH_FS, MESH_VS, PICK_FS, PICK_VS, POINT_FS, POINT_SIMPLE_FS, POINT_SIMPLE_VS, POINT_VS, RECT_FS, RECT_VS, RIBBON_FS, RIBBON_STEPS, RIBBON_VS, SEGMENT_FS, SEGMENT_VS, makeProgram, uniformOf, xySmoothResample } from "./40_gl";
import { acquireGLHost } from "./42_glhost";
import { lodCopyGrid, lodDecodeLogU8, lodDrawDensityTier, lodDropDensityCache, lodDropPointCache, lodRememberDensity, lodSampleForView, lodWriteGridTexture } from "./45_lod";
import { markOf } from "./55_marks";

// ---------------------------------------------------------------------------
// ChartView
// ---------------------------------------------------------------------------

// ChartView gains methods via prototype augmentation (51–57) and creates
// instance fields ad hoc throughout its lifecycle; the merged index signature
// keeps that dynamic surface type-legal until the class is annotated
// field-by-field.
export interface ChartView {
  [key: string]: any;
}

const MARGIN = { l: 62, r: 14, t: 10, b: 42 };
// Subdivisions across one polar bar's angular span. Mirrored by
// POLAR_BAR_SEGMENTS in python/xy/config.py so the raster exporter flattens the
// same arc; the SVG exporter draws a true `A` arc and needs no count. Sized so
// a full-turn wedge's chord sagitta stays under the XY_POLAR_AA expansion on a
// ~1400-device-px disc — the fragment SDF then trims the strip to an exactly
// round arc (see POLAR_WEDGE_GLSL in 40_gl.ts).
const POLAR_BAR_SEGMENTS = 96;
// Floor on any single wedge's subdivision: two segments keep a strip that still
// brackets the true arc after the AA expansion, even for a hairline slice.
const POLAR_BAR_SEGMENTS_MIN = 2;

// Subdivisions for one wedge of angular width `span` out of `turn`. Mirrors
// `polar_bar_segments` in python/xy/config.py.
//
// The count used to be a flat POLAR_BAR_SEGMENTS per wedge, sized for the worst
// case of a wedge sweeping the whole circle. Almost no wedge does: a 16-sector
// wind rose sweeps 22.5 degrees, so every bar paid 2*(96+1) = 194 vertices for an
// arc that needs six segments, and 50k polar bars fell off a cliff building
// ~9.7M vertices a frame instead of ~700k. Sagitta is quadratic in the
// per-segment angle, so holding `span / n` fixed holds the flattening error
// fixed: the honest count is exactly proportional, which reproduces 96 at a full
// turn and preserves the bound for everything narrower. §28 — a recorded formula
// over the AUTHORED angular width, never a view-dependent choice, so zooming and
// exporting cannot change it.
function xyPolarBarSegments(span, turn) {
  // An unmeasurable span falls back to the full-turn count: under-subdividing a
  // wide wedge is a visible facet, and paying for one is not.
  if (!(turn > 0) || !Number.isFinite(span)) return POLAR_BAR_SEGMENTS;
  const scaled = Math.ceil(POLAR_BAR_SEGMENTS * (Math.abs(span) / turn));
  return Math.max(POLAR_BAR_SEGMENTS_MIN, Math.min(POLAR_BAR_SEGMENTS, scaled));
}
// Uniform room outside the outer ring for angular tick labels. Mirrored by
// _POLAR_LABEL_ROOM in python/xy/_svg.py.
const POLAR_LABEL_ROOM = 30;
// Radial tick labels run along a spoke this many degrees off theta zero, and
// angular labels sit this many px outside the rim. Mirrored by
// _POLAR_RLABEL_DEG / _POLAR_TICK_GAP in python/xy/_svg.py.
const POLAR_LABEL_ROOM_MAX = 90;
const POLAR_RLABEL_DEG = 22.5;
const POLAR_TICK_GAP = 8;
// Direction theta=0 points, in radians ccw from east. Mirrored by THETA_ZERO in
// python/xy/_svg.py; the wire carries the letters so one table serves all
// renderers.
const THETA_ZERO = { E: 0, N: Math.PI / 2, W: Math.PI, S: -Math.PI / 2 };
// Gutter reserved for a legend beside a disc. A cartesian legend overlays the
// plot because data rarely reaches a corner; a disc inscribed in its rect leaves
// no corner at all, so an inside legend lands on the marks — an `upper right` box
// covered a wind rose's whole north-east quadrant and the outer radial label
// under it.
//
// A FRACTION OF THE CANVAS, clamped, rather than a measurement of the label set:
// every renderer knows the canvas width to the pixel, so all three reserve the
// identical box, while a measured reservation would drift with each renderer's
// font metrics (system-ui here, DejaVu in the exporters). A flat constant was
// tried first and is the wrong shape — 96 px ellipsized `Partner  (30%)`, an
// ordinary pie slice's default name, while being a fifth of a phone canvas and a
// fifteenth of a wide one. A label still wider than the gutter ellipsizes with
// its full text in `title`/ARIA.
// Mirrored by `_polar_legend_room` in python/xy/_svg.py.
const POLAR_LEGEND_ROOM_FRACTION = 0.22;
const POLAR_LEGEND_ROOM_MIN = 120;
const POLAR_LEGEND_ROOM_MAX = 200;

// `Math.floor`, not `Math.round`: Python and JavaScript disagree about half-way
// cases, and the two must land on the same integer pixel.
function xyPolarLegendRoom(width) {
  const scaled = Math.floor(Number(width) * POLAR_LEGEND_ROOM_FRACTION);
  return Math.min(POLAR_LEGEND_ROOM_MAX, Math.max(POLAR_LEGEND_ROOM_MIN, scaled));
}

const POLAR_LEGEND_BAND = 64;
// DejaVu Sans advances at 16 px, generated beside python/xy/_fontmetrics.py
// and the native rasterizer. Layout must retain proportional glyph metrics:
// character count makes "WWWW" and "iiii" reserve the same (wrong) width.
const XY_FONT_BASE_PX = 16;
const XY_ASCII_FIRST = 32;
const XY_ASCII_LAST = 126;
const XY_ASCII_ADVANCES = [
  5, 6, 7, 13, 10, 15, 12, 4, 6, 6, 8, 13, 5, 6, 5, 5, 10, 10, 10, 10,
  10, 10, 10, 10, 10, 10, 5, 5, 13, 13, 13, 8, 16, 11, 11, 11, 12, 10, 9, 12,
  12, 5, 5, 10, 9, 14, 12, 13, 10, 13, 11, 10, 10, 12, 11, 16, 11, 10, 11, 6,
  5, 6, 13, 8, 8, 10, 10, 9, 10, 10, 6, 10, 10, 4, 4, 9, 4, 16, 10, 10,
  10, 10, 7, 8, 6, 10, 9, 13, 9, 9, 8, 10, 5, 10, 13,
];
const XY_MISSING_ADVANCE = 16;
// Canvas measureText() returns advances while the DOM clamp below operates on
// painted element rectangles. Keep a small guard for an outside y title so
// font rasterization/rounding cannot consume its authored title-to-tick gap.
const Y_TITLE_MEASURE_SAFETY_PX = 2;

// Greedy word wrap of already newline-split lines. Mirrors `wrap_lines` in
// python/xy/_textblock.py, and matches what CSS `white-space: pre-line` does to
// the same string: authored newlines are hard breaks, runs of other whitespace
// collapse to one space, breaks are only taken at a space, and a word wider than
// the limit keeps its own line and overflows (no `overflow-wrap` is set).
function xyWrapLines(lines, advance, maxWidth) {
  const wrapped = [];
  for (const line of lines) {
    const words = String(line).split(/\s+/).filter((word) => word.length);
    if (!words.length) {
      wrapped.push("");
      continue;
    }
    let current = words[0];
    for (const word of words.slice(1)) {
      const candidate = `${current} ${word}`;
      if (advance(candidate) <= maxWidth) current = candidate;
      else {
        wrapped.push(current);
        current = word;
      }
    }
    wrapped.push(current);
  }
  return wrapped;
}

function xyTextAdvance(text, fontSize) {
  let units = 0;
  for (const char of String(text)) {
    const code = char.codePointAt(0) ?? 0;
    units += code >= XY_ASCII_FIRST && code <= XY_ASCII_LAST
      ? XY_ASCII_ADVANCES[code - XY_ASCII_FIRST]
      : XY_MISSING_ADVANCE;
  }
  return Number(fontSize) * units / XY_FONT_BASE_PX;
}

const COLORBAR_THICKNESS = 18;
const COLORBAR_GAP = 24;
const COMPACT_COLORBAR_GAP = 8;
// A compact vertical colorbar keeps its two EXTREME tick labels, stacked above
// and below the gradient rather than beside it. Hiding every tick left an
// unlabelled gradient — a colour ramp with no numbers on it says nothing at all,
// so the compact form was not a smaller version of the chrome but the absence of
// it. Stacking is what makes the fix free: a side gutter wide enough for `0.25`
// cost 36 px of plot width, which is the very thing the compact collapse exists
// to protect, while two centred labels overflow the 18 px bar by ~4 px a side and
// fit inside the gap that is already reserved. Interior ticks and the rotated
// title are what a phone-width chart genuinely cannot afford; the title stays
// readable through the box's own `title`/ARIA text.
const COMPACT_COLORBAR_LABEL_GAP = 3;
let XY_A11Y_ID = 0;
// Legend hover emphasis (interaction spec §9): opacity kept by non-hovered series on
// the marks canvas, and by non-hovered rows in the legend box itself.
const LEGEND_DIM_OPACITY = 0.2;
const LEGEND_DIM_ROW = 0.4;
// Legend click-toggle (interaction spec §10): opacity of a toggled-off row.
const LEGEND_OFF_ROW = 0.35;
// SVG gradient ids resolve document-wide; a module counter keeps every chart
// instance's legend swatch ramps distinct.
let legendGradientSeq = 0;
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
//
// The browser cap is *process-wide* — shared across every same-origin iframe —
// but the machinery above is per-document, so it sees only its own charts. A
// page that puts each chart in its own iframe (docs sites, SaaS dashboards,
// the FastAPI gallery example) would therefore blow the cap: no per-document
// governor ever releases (each frame is under budget on its own), the browser
// LRU-evicts live charts, and the evicted charts fight to recover and re-evict
// — a scroll-driven "Too many active WebGL contexts" storm. The governor
// closes that gap by sharing one budget across same-origin frames over a
// BroadcastChannel (§18): each frame announces its live-context count, and any
// frame over the shared budget sheds its own *off-screen* views (never a
// visible one — a neighbor loading must not blank a chart the user is looking
// at). Cross-origin frames cannot share a channel and fall back to the
// per-document behavior. Over-counting a crashed frame that never said goodbye
// is safe: it only lowers the effective budget, releasing a few extra
// off-screen contexts that revive on demand — it never evicts or blanks.
const XY_CONTEXT_GOVERNOR = {
  views: new Set(),
  seq: 1,
  hiddenReleaseChannel: null,
  hiddenReleaseQueue: [],
  // Cross-frame coordination (initialized lazily on first register()).
  frameId: null,
  channel: null,
  foreign: null, // Map<frameId, liveCount> reported by other same-origin frames
  _announcedLive: -1,
  _crossFrameReady: false,
  _rebalanceScheduled: false,
  budget() {
    const v = typeof window !== "undefined" ? (window as any).XY_CONTEXT_BUDGET : null;
    // 12 leaves headroom under Chrome's ~16 so host-page GL (maps, editors)
    // does not push chart contexts into browser-side eviction.
    return Number.isFinite(v) && v >= 1 ? Math.floor(v) : 12;
  },
  register(view) {
    this._initCrossFrame();
    this.views.add(view);
  },
  unregister(view) {
    view._ctxPendingReservation = false;
    this.views.delete(view);
    this._announceLive();
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
    // A context just came live. Shed our own off-screen views if that pushed
    // the shared budget over, then tell peer frames the new count so theirs
    // can shed too (the newly visible chart stays; off-screen ones give way).
    this._rebalance();
    this._announceLive();
  },
  cancel(requester) {
    requester._ctxPendingReservation = false;
  },
  // --- Cross-frame budget sharing over BroadcastChannel (§18) ---------------
  // Same-origin frames share one WebGL-context budget so a per-chart-iframe
  // page cannot collectively exceed the browser's process-wide cap. Guarded
  // and lazy: a lone top-level page opens a channel but never hears a peer, so
  // foreignLive() stays 0 and every path below is a no-op — identical to the
  // per-document behavior. Cross-origin frames get their own opaque channel
  // scope (or none) and likewise fall back.
  _initCrossFrame() {
    if (this._crossFrameReady) return;
    this._crossFrameReady = true;
    this.foreign = new Map();
    if (typeof BroadcastChannel === "undefined") return;
    try {
      this.frameId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
      this.channel = new BroadcastChannel("xy-webgl-context-governor");
      this.channel.onmessage = (event) => this._onForeignMessage(event.data);
      // Announce arrival so already-open frames re-advertise their counts, and
      // drop our contribution from theirs when we go away.
      this._post({ t: "hello", id: this.frameId });
      if (typeof window !== "undefined" && window.addEventListener) {
        // `pagehide` fires on real unload AND when the document is frozen into
        // the back/forward cache; either way peers should stop counting us (a
        // frozen frame can't respond to shed requests). `pageshow` with
        // persisted=true is a bfcache restore: re-announce so peers add us back
        // — without it a restored frame stays absent from the shared budget and
        // the page can silently exceed the browser cap.
        window.addEventListener("pagehide", () => this._post({ t: "bye", id: this.frameId }));
        window.addEventListener("pageshow", (event) => {
          if (!event || !event.persisted) return;
          // Peers may have come and gone while we were frozen, and a departed
          // peer sent its `bye` to a channel we could not hear. Drop the stale
          // map and rebuild it from live peers' replies to our `hello` rather
          // than counting contexts that no longer exist.
          this.foreign.clear();
          this._announcedLive = -1; // force the announcement below to re-send
          this._post({ t: "hello", id: this.frameId }); // relearn peers' counts
          this._announceLive(true); // and re-advertise ours
        });
      }
    } catch (_err) {
      this.channel = null; // sandboxed context: stay per-document
    }
  },
  _post(msg) {
    try {
      if (this.channel) this.channel.postMessage(msg);
    } catch (_err) {
      /* channel closed mid-teardown */
    }
  },
  _onForeignMessage(msg) {
    if (!msg || !this.foreign || msg.id === this.frameId) return;
    if (msg.t === "live") {
      this.foreign.set(msg.id, msg.n | 0);
      this._rebalance();
    } else if (msg.t === "hello") {
      // A frame joined: re-advertise so it learns our current count.
      this._announceLive(true);
    } else if (msg.t === "bye") {
      this.foreign.delete(msg.id);
    }
  },
  localLive() {
    let n = 0;
    for (const view of this.views) {
      if (view.gl && !view._glLost && !view._destroyed) n += 1;
    }
    return n;
  },
  foreignLive() {
    let n = 0;
    if (this.foreign) for (const count of this.foreign.values()) n += count;
    return n;
  },
  // Broadcast this frame's live-context count when it changes (deduped so a
  // burst of releases collapses to one message). `force` re-sends the current
  // count in reply to a peer's hello even when it is unchanged.
  _announceLive(force = false) {
    if (!this.channel) return;
    const n = this.localLive();
    if (!force && n === this._announcedLive) return;
    this._announcedLive = n;
    this._post({ t: "live", id: this.frameId, n });
  },
  // Shared budget crossed (a peer announced, we acquired, or one of our charts
  // scrolled off): release the single least-recently-visible *off-screen* view.
  // Visible views are never released here — the shared cap can only be honored
  // by dropping off-screen contexts, and blanking a chart the user is looking
  // at because a sibling frame loaded is worse than the documented
  // >budget-simultaneously-visible limit.
  //
  // One release per call, not the whole computed excess: several frames all see
  // the same over-budget snapshot at once, and if each dropped the full deficit
  // they would collectively over-release (N frames each shedding K → N×K gone).
  // Shedding one and re-arming on a task lets every frame's release announce and
  // be observed before the next round, so the page converges on the budget
  // instead of overshooting it. Re-arming (rather than stopping) also means a
  // frame that must shed several never under-releases when peers are quiet.
  _rebalance() {
    if (this.localLive() + this.foreignLive() - this.budget() <= 0) return;
    let target = null;
    for (const view of this.views) {
      if (view.gl && !view._glLost && !view._destroyed && !view._ctxVisible) {
        if (!target || (view._ctxSeenSeq || 0) < (target._ctxSeenSeq || 0)) target = view;
      }
    }
    if (!target || !target._releaseContext()) return;
    if (this.localLive() + this.foreignLive() - this.budget() > 0 && !this._rebalanceScheduled) {
      this._rebalanceScheduled = true;
      setTimeout(() => {
        this._rebalanceScheduled = false;
        this._rebalance();
      }, 0);
    }
  },
  // Releasing a context takes a synchronous framebuffer readback. Queue one
  // chart per task when a document is hidden so visibilitychange itself stays
  // cheap and a many-chart page cannot monopolize the event-loop turn.
  scheduleHiddenReleases() {
    if (this.hiddenReleaseChannel !== null) return;
    this.hiddenReleaseQueue = Array.from(this.views);
    const channel = new MessageChannel();
    this.hiddenReleaseChannel = channel;
    channel.port1.onmessage = () => {
      if (
        typeof document === "undefined" ||
        document.visibilityState !== "hidden"
      ) {
        this.cancelHiddenReleases();
        return;
      }
      let view = null;
      while (this.hiddenReleaseQueue.length && !view) {
        const candidate = this.hiddenReleaseQueue.shift();
        if (
          !candidate._destroyed &&
          candidate.gl &&
          !candidate._glLost &&
          !candidate.gl.isContextLost()
        ) view = candidate;
      }
      if (!view) {
        this.cancelHiddenReleases();
        return;
      }
      view._releaseContext();
      channel.port2.postMessage(null);
    };
    channel.port2.postMessage(null);
  },
  cancelHiddenReleases() {
    this.hiddenReleaseChannel?.port1.close();
    this.hiddenReleaseChannel?.port2.close();
    this.hiddenReleaseChannel = null;
    this.hiddenReleaseQueue = [];
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

export class ChartView {
  constructor(el, spec, buffer, comm) {
    if (spec.protocol !== PROTOCOL) {
      el.textContent =
        `xy: protocol mismatch (client speaks ${PROTOCOL}, kernel sent ${spec.protocol}). ` +
        "Update the xy package and restart the kernel.";
      throw new Error("protocol mismatch");
    }
    this.spec = spec;
    // Title y/pad placement is a binary geometry column, so it must be
    // available before the constructor's first layout pass.
    this._payload = buffer;
    this.interaction = spec.interaction || {};
    this.markStyle = spec.mark_style || {};
    this.axes = this._normalizeAxes(spec);
    this.comm = comm;
    this.seq = 0;
    this._densityStamp = 0;
    this._viewRequestBurstStart = null;
    this._viewAnim = null;
    this._animRaf = null;
    this._dataAnim = null;
    this._dataAnimRaf = null;
    this._transitionOldTraces = null;
    this._transitionView = null;
    this._wheelZoomRaf = null;
    this._pendingWheelZoom = null;
    this._lastLabelDraw = null;
    this._lutCache = new Map();
    this._listeners = [];
    this._glPrograms = [];
    this._progCache = new Map();
    this._bufSeq = 0;
    this._destroyed = false;
    this._resizeRaf = null;
    this._pendingResize = null;
    this._resizeNeedsMeasure = false;
    this._hoverId = -1;
    this._hoverTarget = null;
    this._viewEventRaf = null;
    this._linkedSource = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    // pan | none | zoom | internal selection modes. Browser-local active drag
    // action: the configured default resolves after GL setup, when pickability
    // is known (§ _resolveDefaultDragAction). Pan is the default outcome; the
    // modebar can toggle back into `none` so embedded charts do not trap page
    // scroll.
    this.dragMode = "none";
    this._interactionSeq = 0;

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
    this._glLost = false;
    this._ctxReleasedExt = null;
    this._ctxReleases = 0;
    this._ctxRecoveries = 0;
    // A governed release's webglcontextlost event is dispatched a task later;
    // restoreContext() called before it lands is silently dropped by Chromium,
    // so recovery that races ahead is deferred until the loss handler fires.
    this._ctxLostPending = false;
    this._ctxRecoverRequested = false;
    this._ctxVisible = xyInitiallyVisible(el);
    // Top-level documents default to one shared WebGL2 host. Child frames keep
    // the existing governed per-chart path unless explicitly opted in: the
    // browser's context quota spans frames, while a WebGL context cannot cross
    // their realm/document boundary.
    this._glHost = null;
    this._present2d = null;
    this._sharedGlAttempted = false;
    this._governorRegistered = false;
    this._glHostRecoveryTimer = null;
    this._glHostRecoveryDelay = 0;
    if (this._ctxVisible) this._ctxSeenSeq = XY_CONTEXT_GOVERNOR.seq++;
    this._contextLossCount = 0;
    this._contextRestoreCount = 0;
    this._contextRecoveryError = null;
    try {
      this._initGl(buffer);
    } catch (err) {
      // Initial construction has no recovery handler yet and the public entry
      // points intentionally let the exception surface. Leave a useful DOM
      // fallback behind for browsers without WebGL2; recovery attempts catch
      // the same error themselves and therefore never replace their canvas.
      if (this._governorRegistered) {
        XY_CONTEXT_GOVERNOR.unregister(this);
        this._governorRegistered = false;
      }
      this._glHost?.release(this);
      this._glHost = null;
      if (String(err && err.message || err) === "webgl2 unavailable") {
        this.root.textContent = "xy: WebGL2 unavailable in this browser.";
      }
      throw err;
    }
    this.canvas.dataset.xyCtx = "live";
    this.view0 = this._clampView({
      ranges: Object.fromEntries(Object.entries(this.axes).map(([id, axis]: any) => [id, [...axis.range]])),
    });
    this.view = this._copyView(this.view0);
    this.dragMode = this._resolveDefaultDragAction();
    this._initA11y();
    this.root.dataset.xyContextState = "ready";
    this._initContextLossRecovery();
    this._armContextVisibilityWatch();
    this._initViewState(); // durable-state controller + history before gestures
    this._initInteraction();
    this._buildModebar(this.root); // after theme (icon color) + canvas (cursor)
    this._initAxisBands(); // after modebar so bands sit under its z-order

    if ((this.fluid || this.fluidH) && typeof ResizeObserver !== "undefined") {
      this._ro = new ResizeObserver((entries) => {
        const r = entries[entries.length - 1].contentRect;
        if (r.width || r.height) this._queueResize(r.width, r.height);
      });
      this._ro.observe(this.root);
    }
    this._armVisibilityResizeWatch();
    this._armDprWatch();

    this._initLinkedCharts();

    this._themeWatch = window.matchMedia("(prefers-color-scheme: dark)");
    this._onScheme = () => this.refreshTheme();
    this._themeWatch.addEventListener?.("change", this._onScheme);
    // Framework theme switches usually toggle a class (for example `.dark`)
    // or data-theme on the chart or an ancestor without changing the OS color
    // scheme. Watch that cascade path as well so canvas/SVG paint refreshed
    // from --chart-* tokens stays in sync with the CSS-owned chart chrome.
    if (typeof MutationObserver !== "undefined") {
      this._themeMutationObserver = new MutationObserver(() => this.refreshTheme());
      for (let node = this.root; node; node = node.parentElement) {
        this._themeMutationObserver.observe(node, {
          attributes: true,
          attributeFilter: ["class", "data-theme", "style"],
        });
      }
    }

    this._unsubscribeComm = comm ? comm.onMessage((msg, buffers) => this._onKernelMsg(msg, buffers)) : null;
    if (this._startEntranceAnimation) this._startEntranceAnimation();
    else this.draw();
  }

  _layout() {
    // Plot rect from the current size — margins fixed, data area flexes.
    const compact = this.size.w < 520;
    // Explicit padding (spec.padding = [top,right,bottom,left]) overrides the
    // label-aware defaults — zero padding gives an edge-to-edge sparkline.
    const pad = Array.isArray(this.spec.padding) ? this.spec.padding : null;
    const colorbar = this.spec.colorbar;
    const verticalColorbar = colorbar && colorbar.orientation !== "horizontal";
    const horizontalColorbar = colorbar && colorbar.orientation === "horizontal";
    const axesColorbar = colorbar && colorbar.placement === "axes";
    // Fluid charts have to remain useful inside dashboard columns. On compact
    // widths, cap only oversized authored horizontal padding and collapse a
    // vertical colorbar to its gradient; the full tick/title chrome returns
    // automatically when the container widens again.
    const responsivePad = this.fluid && compact && pad;
    this._compactVerticalColorbar = Boolean(
      this.fluid && compact && verticalColorbar && !axesColorbar
    );
    const automaticColorbarGap = colorbar && colorbar.pad === 0 ? 0 : 24;
    const colorbarRightRoom = verticalColorbar
      ? axesColorbar
        ? 44 + (colorbar.label ? 18 : 0)
        : (this._compactVerticalColorbar
          ? COMPACT_COLORBAR_GAP + COLORBAR_THICKNESS + 8
          : 62 + automaticColorbarGap + (colorbar.label ? 18 : 0))
      : 0;
    const colorbarBottomRoom = horizontalColorbar
      ? (axesColorbar ? 24 : 38) + (colorbar.label ? 16 : 0)
      : 0;
    const baseRight = pad ? (responsivePad ? Math.min(pad[1], 8) : pad[1]) : compact ? 8 : MARGIN.r;
    const marginRight = baseRight + colorbarRightRoom;
    const marginTop = pad ? pad[0] : compact ? 6 : MARGIN.t;
    const baseBottom = pad ? pad[2] : compact ? 36 : MARGIN.b;
    const bottomAxes = Object.values<any>(this.axes || {}).filter((axis: any) =>
      axis && String(axis.id || "").startsWith("x") &&
      (this._axisTickLabelSides(axis).includes("bottom") || axis.side !== "top") &&
      this._axisTickLabelStrategy(axis) !== "none");
    const hasBottomAxis = bottomAxes.length > 0;
    // A named x axis can own the top edge even when the primary x axis stays
    // on the bottom. Reserve one shared gutter for every top-side x axis;
    // multiple axes on the same side intentionally overlay until axis offsets
    // become part of the public API (the same rule used by secondary y axes).
    const topAxes = Object.values<any>(this.axes || {}).filter((axis: any) =>
      axis && String(axis.id || "").startsWith("x") &&
      (this._axisTickLabelSides(axis).includes("top") || axis.side === "top") &&
      this._axisTickLabelStrategy(axis) !== "none");
    const hasTopAxis = topAxes.length > 0;
    const authoredLeft = pad
      ? (responsivePad ? Math.min(pad[3], 46) : pad[3])
      : (compact ? 46 : MARGIN.l);
    // Width the title wraps at. Resolved from the authored/default gutters
    // (`baseRight`, before colorbar and right-axis room) rather than the final
    // plot rect, because the measured left gutter depends on the plot height,
    // which depends on the title band — wrapping at the final width would be
    // circular. Mirrors `_title_wrap_width` in python/xy/_svg.py.
    //
    // The title DIV wraps whether or not layout accounts for it (white-space is
    // `pre-line`), so measuring one line and drawing two put the first line
    // above the canvas: a compact Wind Rose title lost about 10 px off its top.
    // `_positionTitles` caps the element at this same width, so what the DOM
    // wraps is exactly what is reserved here.
    this._titleWrapWidth = Math.max(40, this.size.w - authoredLeft - baseRight);
    const titleRoom = this._titleEntries().reduce((room, entry) => {
      const authoredSize = Number.parseFloat(entry.style?.["font-size"]);
      const titleFontSize = Number.isFinite(authoredSize)
        ? authoredSize
        : this._slotFontSize("title", 14);
      const measured = this._estimateTickLabel(
        entry.text, titleFontSize, this._titleWrapWidth,
      ).h;
      const pad = Number.isFinite(Number(entry.pad)) ? Number(entry.pad) : 8;
      const candidate = entry.automatic_y !== false
        ? Math.max(compact ? 26 : 30, measured + pad)
        : (Number(entry.y ?? 1) >= 1 ? measured + pad : 0);
      return Math.max(room, candidate);
    }, 0);
    this._titleRoom = titleRoom;
    const provisionalTopAxisRoom = hasTopAxis ? (compact ? 26 : 32) : 0;
    const provisionalBottomAxisRoom = hasBottomAxis ? (compact ? 36 : MARGIN.b) : 0;
    const provisionalTop = marginTop + titleRoom + provisionalTopAxisRoom;
    const provisionalBottom =
      Math.max(baseBottom, provisionalBottomAxisRoom) + colorbarBottomRoom;
    const plotHeight = Math.max(40, this.size.h - provisionalTop - provisionalBottom);
    // Explicit padding is a floor, not permission to clip. Long numeric or
    // categorical ticks and an outside y title reserve the room their actual
    // strings need before the plot rectangle is fixed.
    const measuredLeft = Math.max(authoredLeft, this._yAxisLeftRoom(plotHeight));
    const rightAxes = Object.values<any>(this.axes || {}).filter((axis: any) =>
      axis && String(axis.id || "").startsWith("y") &&
      (this._axisTickLabelSides(axis).includes("right") || axis.side === "right") &&
      this._axisTickLabelStrategy(axis) !== "none");
    // The vertical colorbar shifts right by this room (see _positionColorbar);
    // the Python SVG/raster exporters apply the identical 42/54 rule.
    this._rightAxisRoom = rightAxes.length ? (compact ? 42 : 54) : 0;
    const right = marginRight + this._rightAxisRoom;
    // Measurement can consume spare canvas room, but it must not move the
    // y-axis anchor past the viewport on a chart whose authored padding has
    // already reached the 40 px plot floor. In that compact case the tick
    // labels retain their full text in `title`/ARIA and ellipsize in bounds.
    const measuredLeftCap = Math.max(authoredLeft, this.size.w - right - 40);
    const marginLeft = Math.min(measuredLeft, measuredLeftCap);
    const plotWidth = Math.max(40, this.size.w - marginLeft - right);
    const measuredTopAxisRoom = this._xAxisRoom("top", plotWidth);
    const measuredBottomAxisRoom = this._xAxisRoom("bottom", plotWidth);
    const topAxisRoom = hasTopAxis
      ? Math.max(provisionalTopAxisRoom, measuredTopAxisRoom)
      : 0;
    this._topAxisRoom = topAxisRoom;
    const bottomAxisRoom = hasBottomAxis
      ? Math.max(provisionalBottomAxisRoom, measuredBottomAxisRoom)
      : 0;
    this._bottomAxisRoom = bottomAxisRoom;
    const top = marginTop + titleRoom + topAxisRoom;
    const marginBottom =
      (measuredBottomAxisRoom ? Math.max(baseBottom, measuredBottomAxisRoom) : baseBottom)
      + colorbarBottomRoom;
    this.plot = {
      x: marginLeft,
      y: top,
      w: plotWidth,
      h: Math.max(40, this.size.h - top - marginBottom),
    };
    // The box legends place themselves in. Null means "the plot rect", which is
    // every cartesian chart and every polar chart that reserves no gutter — kept
    // null rather than aliased to `this.plot`, because `_recutPolarPlot` REPLACES
    // that object and an alias would freeze the pre-recut geometry.
    this._legendRect = null;
    this._recutPolarPlot(compact);
  }

  // Side and px a polar legend gutter claims, or null when nothing is reserved:
  // a non-polar figure, no legend rows, an authored `anchor` (an explicit
  // plot-relative placement the author owns), or an authored 4-tuple `padding`
  // (which already states the box the plot should occupy, and is the documented
  // way to hand-reserve a caption band).
  // Mirrors `_polar_legend_reserve` in python/xy/_svg.py.
  _polarLegendReserve(compact) {
    const s = this.spec || {};
    if (s.coords !== "polar" || s.show_legend === false) return null;
    if (Array.isArray(s.padding) && s.padding.length === 4) return null;
    const options = s.legend || {};
    if (Array.isArray(options.anchor) && [2, 4].includes(options.anchor.length)) return null;
    const hasRows = (options.items || []).length > 0
      || (s.extra_legends || []).length > 0
      || (s.traces || []).some((t) =>
        t && (t.name || (t.color && t.color.mode === "categorical")));
    if (!hasRows) return null;
    if (compact) return { side: "bottom", room: POLAR_LEGEND_BAND };
    const loc = String(options.loc || "upper right");
    return {
      side: loc.includes("left") ? "left" : "right",
      room: xyPolarLegendRoom(this.size.w),
    };
  }

  // Re-cut the plot rect for a disc. Mirrors `_recut_polar_plot` in
  // python/xy/_svg.py; the two must agree or the same chart renders at a
  // different size and centre in the browser than in an export.
  //
  // Cartesian tick-label gutters hold labels hugging the left and bottom edges.
  // A polar chart rings its labels around the rim instead, so those gutters are
  // symmetrised (not simply zeroed — a colorbar that genuinely claimed space
  // keeps it), and a uniform allowance is reserved all the way around.
  // Room outside the ring for the angular tick labels. Measured rather than
  // fixed: authored category names are far wider than an angle, and a constant
  // allowance hard-clipped them. Mirrors `_polar_label_room` in
  // python/xy/_svg.py — including the ceiling, past which a pathological label
  // truncates instead of shrinking the disc away.
  _polarLabelRoom(axis) {
    // A category axis carries its authored names in `categories` and usually
    // has no `tick_labels` at all (`_axisTicks` hands the categories straight
    // to `categoryTicks`), so measuring only `tick_labels` fell back to the
    // uniform default and long names spilled over the disc.
    const labels = (axis && axis.tick_labels)
      || (axis && axis.kind === "category" ? axis.categories : null);
    if (!Array.isArray(labels) || !labels.length) return POLAR_LABEL_ROOM;
    const size = this._axisStyleNumber(axis, "tick_label_size", 11);
    let widest = 0;
    for (const text of labels) widest = Math.max(widest, xyTextAdvance(String(text), size));
    return Math.min(
      POLAR_LABEL_ROOM_MAX,
      Math.max(POLAR_LABEL_ROOM, widest + POLAR_TICK_GAP + 4),
    );
  }

  _recutPolarPlot(compact = false) {
    if (this.spec?.coords !== "polar") return;
    const xAxisSpec = this._axis("x") || {};
    // Hiding the angular tick labels removes the LABEL inset, not the legend
    // gutter. Returning here skipped `_polarLegendReserve` outright, and since
    // `_layout` clears `_legendRect` just before this call, legend sizing and
    // positioning then fell back to `this.plot` and drew the legend on top of
    // the marks. Track it and skip only the inset.
    const labelsHidden = this._axisTickLabelStrategy(xAxisSpec) === "none";
    // A legend gutter comes off the canvas edge FIRST, before the disc is fitted
    // to what remains, so the disc never occupies the gutter and the legend
    // never occupies the disc. Mirrors the same block in `_recut_polar_plot`.
    let canvasX0 = 0;
    let canvasW = this.size.w;
    let canvasH = this.size.h;
    const reserve = this._polarLegendReserve(compact);
    if (reserve) {
      const p0 = { ...this.plot };
      if (reserve.side === "left") {
        canvasX0 = reserve.room;
        this._legendRect = { x: 0, y: p0.y, w: reserve.room, h: p0.h };
        p0.x = Math.max(p0.x, reserve.room);
      } else if (reserve.side === "right") {
        canvasW -= reserve.room;
        this._legendRect = { x: canvasW, y: p0.y, w: reserve.room, h: p0.h };
      } else {
        canvasH -= reserve.room;
        this._legendRect = { x: p0.x, y: canvasH, w: p0.w, h: reserve.room };
      }
      p0.w = Math.max(40, Math.min(p0.w, canvasW - p0.x));
      p0.h = Math.max(40, Math.min(p0.h, canvasH - p0.y));
      this.plot = p0;
    }
    const p = this.plot;
    const reservedTop = p.y;
    const reservedRight = canvasW - p.x - p.w;
    const reservedBottom = canvasH - p.y - p.h;
    const room = labelsHidden ? 0 : this._polarLabelRoom(xAxisSpec);
    // An explicit `padding` states the box the author wants the plot to
    // occupy — usually to reserve a band under the disc for a legend or
    // caption. Reclaiming those gutters below would throw that away, so an
    // authored box is only inset by the uniform label room. Mirrors the same
    // early return in `_recut_polar_plot` (python/xy/_svg.py).
    if (Array.isArray(this.spec.padding) && this.spec.padding.length === 4) {
      const boxW = p.w - 2 * room;
      const boxH = p.h - 2 * room;
      if (boxW >= 40 && boxH >= 40) {
        this.plot = { ...p, x: p.x + room, y: p.y + room, w: boxW, h: boxH };
        this._topAxisRoom = (this._topAxisRoom || 0) + room;
      }
      return;
    }
    const side = Math.max(room, reservedRight);
    // A radial-axis title still lives in the left gutter — a disc gives it no
    // natural home — and it is placed outward past the tick-label room, so a
    // titled radial axis keeps its gutter whole rather than part-reclaimed.
    const yAxis = this._axis("y") || {};
    const titled = !!yAxis.label;
    // `canvasX0` is a left legend gutter; the label room still applies inside
    // it. With no gutter it is 0 and `side >= room`, so this is the old value.
    const left = Math.max(titled ? Math.max(side, p.x) : side, canvasX0 + room);
    const right = canvasW - side;
    // Only the bottom can be symmetrised: the top also holds the figure title,
    // and the bottom keeps its full band when the theta axis has a title of its
    // own (it is drawn there; reclaiming the band pushed it off the canvas).
    const xAxis = this._axis("x") || {};
    // A horizontal colorbar hangs off the plot's bottom edge; extending the
    // rect downward would walk it off the canvas.
    const keepsBottom = !!xAxis.label || this.spec?.colorbar?.orientation === "horizontal";
    const bottomReserve = keepsBottom ? reservedBottom : Math.min(reservedBottom, reservedTop);
    const bottom = canvasH - Math.max(room, bottomReserve);
    const top = reservedTop + room;
    const w = right - left;
    const h = bottom - top;
    if (!(w >= 40) || !(h >= 40)) return;
    this.plot = { ...p, x: left, y: top, w, h };
    // The top slice is angular-label room, so it belongs to the axis
    // reservation: `_positionTitles` anchors at `plot.y - _topAxisRoom`, and
    // without this the title rides the rect down and the topmost angular label
    // lands on top of it. Mirrors the same line in `_recut_polar_plot`.
    this._topAxisRoom = (this._topAxisRoom || 0) + room;
    // Re-square the legend gutter against the FINAL rect so the box tracks the
    // disc it sits beside rather than the pre-recut rect it was cut from.
    if (reserve) {
      const box = this._legendRect;
      if (reserve.side === "bottom") this._legendRect = { ...box, x: this.plot.x, w: this.plot.w };
      else this._legendRect = { ...box, y: this.plot.y, h: this.plot.h };
    }
  }

  _titleEntries() {
    if (Array.isArray(this.spec.title_options) && this.spec.title_options.length) {
      return this.spec.title_options
        .filter((entry) => entry && entry.text)
        .map((entry) => {
          if (!Number.isInteger(entry.geometry)) return entry;
          const values = this._columnView(
            this._payload,
            this.spec.columns[entry.geometry],
          );
          return { ...entry, y: Number(values[0]), pad: Number(values[1]) };
        });
    }
    return this.spec.title
      ? [{ text: this.spec.title, loc: "center", y: 1, pad: 8, automatic_y: true, style: {} }]
      : [];
  }

  _positionTitles() {
    for (const { element: title, entry } of this._titleElements || []) {
      const loc = ["left", "center", "right"].includes(entry.loc) ? entry.loc : "center";
      const x = loc === "left"
        ? this.plot.x
        : loc === "right"
          ? this.plot.x + this.plot.w
          : this.plot.x + this.plot.w / 2;
      const anchorY = entry.automatic_y !== false
        ? this.plot.y - this._topAxisRoom
        : this.plot.y + (1 - Number(entry.y ?? 1)) * this.plot.h;
      const shiftX = loc === "left" ? "0%" : loc === "right" ? "-100%" : "-50%";
      title.style.textAlign = loc;
      title.style.left = `${x}px`;
      title.style.top = `${anchorY}px`;
      // Cap the box at the width `_layout` measured the title band at, so the
      // DOM cannot wrap into more lines than the band reserves. The transform
      // still positions by the element's REAL height, so an agreed line count
      // means the reserved band and the painted block are the same box.
      title.style.maxWidth = `${Math.max(40, Number(this._titleWrapWidth) || 40)}px`;
      title.style.transform = `translate(${shiftX}, calc(-100% - ${Number(entry.pad ?? 8)}px))`;
    }
  }

  _yAxisLeftRoom(plotHeight) {
    let room = 0;
    for (const axis of Object.values<any>(this.axes || {})) {
      if (!axis || !String(axis.id || "").startsWith("y")) continue;
      const labelsOnLeft = this._axisTickLabelSides(axis).includes("left");
      const titleOnLeft = axis.side !== "right";
      if (!labelsOnLeft && !titleOnLeft) continue;
      if (this._axisTickLabelStrategy(axis) === "none") continue;
      const size = Math.max(
        8,
        this._axisStyleNumber(
          axis,
          "tick_label_size",
          this._axisStyleNumber(axis, "tick_size", 11),
        ),
      );
      const angle = Math.abs(Number(this._axisTickLabelAngle(axis) || 0)) * Math.PI / 180;
      const ticks = labelsOnLeft
        ? this._axisTicks(
          axis.id,
          this._axisTickTarget(axis.id, Math.max(3, plotHeight / 45)),
        )
        : { ticks: [], labels: [] };
      let tickRoom = 0;
      for (const value of (ticks.labels || ticks.ticks)) {
        const text = this._axisTickText(axis, value, ticks.step);
        const estimate = this._estimateTickLabel(text, size);
        tickRoom = Math.max(
          tickRoom,
          Math.abs(Math.cos(angle)) * estimate.w + Math.abs(Math.sin(angle)) * estimate.h,
        );
      }
      const length = Math.max(0, this._axisStyleNumber(axis, "tick_length", 0));
      const direction = String(this._axisStyleValue(axis, "tick_direction") || "out");
      const outward = direction === "in" ? 0 : direction === "inout" ? length / 2 : length;
      const tickOffset = labelsOnLeft
        ? outward + Math.max(0, this._axisStyleNumber(axis, "tick_padding", 4))
        : 0;
      let needed = labelsOnLeft ? 4 + tickOffset + tickRoom : 0;
      const rawPosition = axis.label_position;
      const position = typeof rawPosition === "string" ? rawPosition.replace(/-/g, "_") : "";
      if (titleOnLeft && axis.label && !position.startsWith("inside_")) {
        const labelSize = Math.max(8, this._axisStyleNumber(axis, "label_size", 12));
        const gap = Number.isFinite(Number(axis.label_offset))
          ? Number(axis.label_offset)
          : 0.4 * labelSize;
        const labelBlock = this._estimateTickLabel(axis.label, labelSize);
        const rawLabelAngle = Number(axis.label_angle);
        // The default quarter-turn consumes the text block's height. An
        // authored angle projects both dimensions into the left gutter.
        const labelExtent = Number.isFinite(rawLabelAngle)
          ? Math.abs(Math.cos(rawLabelAngle * Math.PI / 180)) * labelBlock.w
            + Math.abs(Math.sin(rawLabelAngle * Math.PI / 180)) * labelBlock.h
          : labelBlock.h;
        needed +=
          Y_TITLE_MEASURE_SAFETY_PX
          + gap
          + labelExtent;
      }
      room = Math.max(room, needed);
    }
    return room;
  }

  _slotFontSize(slot, fallback) {
    const styles = this.spec.dom && this.spec.dom.styles;
    const value = styles && styles[slot] && styles[slot]["font-size"];
    const parsed = parseFloat(String(value ?? ""));
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  }

  _xAxisRoom(side, plotWidth) {
    let room = 0;
    for (const axis of Object.values<any>(this.axes || {})) {
      if (!axis || !String(axis.id || "").startsWith("x")) continue;
      const titleSide = axis.side === "top" ? "top" : "bottom";
      const labelsOnSide = this._axisTickLabelSides(axis).includes(side);
      if (!labelsOnSide && titleSide !== side) continue;
      const strategy = this._axisTickLabelStrategy(axis);
      if (["none", "off"].includes(strategy)) continue;
      const sideAxis = { ...axis, side };
      const size = Math.max(
        8,
        this._axisStyleNumber(
          axis,
          "tick_label_size",
          this._axisStyleNumber(axis, "tick_size", 11),
        ),
      );
      const ticks = this._axisTicks(
        axis.id,
        this._axisTickTarget(axis.id, Math.max(3, plotWidth / (axis.kind === "time" ? 90 : 80))),
      );
      const [lo, hi] = this._axisRange(axis.id);
      const c0 = this._axisCoord(axis, lo);
      const c1 = this._axisCoord(axis, hi);
      const candidates = (labelsOnSide ? (ticks.labels || ticks.ticks) : []).map((value) => ({
        pos: c1 === c0 ? plotWidth / 2 : ((this._axisCoord(axis, value) - c0) / (c1 - c0)) * plotWidth,
        text: this._axisTickText(axis, value, ticks.step),
      }));
      const items = this._layoutTickLabels(sideAxis, "x", candidates);
      const hasAdaptiveLayout = items.some(
        (item) => Number(item.angle || 0) || Number(item.row || 0),
      );
      const hasMultilineTicks = items.some(
        (item) => this._estimateTickLabel(item.text, size).lines.length > 1,
      );
      const position = typeof axis.label_position === "string"
        ? axis.label_position.replace(/-/g, "_") : "center";
      const labelSize = Math.max(8, this._axisStyleNumber(axis, "label_size", 12));
      const labelBlock = titleSide === side && axis.label && !position.startsWith("inside_")
        ? this._estimateTickLabel(axis.label, labelSize) : null;
      const labelExtra = labelBlock
        ? Math.max(0, labelBlock.h - labelSize * 1.2) : 0;
      if (
        !hasAdaptiveLayout
        && !hasMultilineTicks
        && !labelExtra
        && strategy === "auto"
        && this._axisTickLabelAngle(axis) === null
      ) {
        continue;
      }
      let extent = 0;
      let rows = 0;
      for (const item of items) {
        const measured = this._estimateTickLabel(item.text, size);
        const angle = Math.abs(Number(item.angle || 0)) * Math.PI / 180;
        extent = Math.max(
          extent,
          Math.abs(Math.sin(angle)) * measured.w + Math.abs(Math.cos(angle)) * measured.h,
        );
        rows = Math.max(rows, Number(item.row || 0));
      }
      const rawPadding = this._axisStyleValue(axis, "tick_padding");
      const rawLength = this._axisStyleValue(axis, "tick_length");
      const rawWidth = this._axisStyleValue(axis, "tick_width");
      const hiddenSentinel = Number(rawLength) === 0 && Number(rawWidth) === 0;
      const authored = rawPadding !== undefined
        || (rawLength !== undefined && !hiddenSentinel);
      let offset = side === "top" ? 7 : 16;
      if (authored) {
        const length = Math.max(0, this._axisStyleNumber(axis, "tick_length", 0));
        const direction = String(this._axisStyleValue(axis, "tick_direction") || "out");
        const outward = direction === "in" ? 0 : direction === "inout" ? length / 2 : length;
        offset = outward + this._axisStyleNumber(axis, "tick_padding", 4)
          + (side === "top" ? size * 0.2 : size * 0.8);
      }
      room = Math.max(room, 4 + offset + rows * (size + 4) + extent + labelExtra);
    }
    return room;
  }

  _normalizeAxes(spec) {
    const axes = { ...(spec.axes || {}) };
    if (spec.x_axis) axes.x = spec.x_axis;
    if (spec.y_axis) axes.y = spec.y_axis;
    for (const [id, axis] of Object.entries<any>(axes)) {
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
    const axis = this._axis(axisId);
    const scale = axis.scale;
    return scale === "log" ? (axis.nonpositive === "mask" ? 3 : 1)
      : scale === "symlog" ? 2 : 0;
  }

  _axisConstant(axisId) {
    const constant = Number(this._axis(axisId).constant);
    return Number.isFinite(constant) && constant > 0 ? constant : 1;
  }

  _axisIds() {
    return Object.keys(this.axes || {});
  }

  _copyView(view) {
    const ranges: any = {};
    for (const axisId of this._axisIds()) {
      const range = view?.ranges?.[axisId] || this._axis(axisId).range || [0, 1];
      ranges[axisId] = [Number(range[0]), Number(range[1])];
    }
    const x = ranges.x || [0, 1];
    const y = ranges.y || [0, 1];
    return { ranges, x0: x[0], x1: x[1], y0: y[0], y1: y[1] };
  }

  _viewFrom(next, base = this.view) {
    const ranges = {};
    for (const axisId of this._axisIds()) {
      const source = next?.ranges?.[axisId]
        || (axisId === "x" && next?.x0 !== undefined ? [next.x0, next.x1] : null)
        || (axisId === "y" && next?.y0 !== undefined ? [next.y0, next.y1] : null)
        || base?.ranges?.[axisId]
        || this._axis(axisId).range
        || [0, 1];
      ranges[axisId] = [Number(source[0]), Number(source[1])];
    }
    return this._copyView({ ranges });
  }

  _axisPolicy(name) {
    const configured = this.interaction?.[name];
    const ids = (!Array.isArray(configured) || !configured.length)
      ? this._axisIds()
      : (() => {
        const declared = new Set(this._axisIds());
        return [...new Set(configured.filter((axisId) => declared.has(axisId)))];
      })();
    // Polar interaction is deliberately small (polar-axes.md §8): wheel zoom
    // is RADIAL-ONLY (the y axis carries r), and pan is disabled rather than
    // half-working — a cartesian pan would shift the theta range and rescale
    // the disc as if the chart were rectilinear, which is exactly what it
    // looked like: wrong.
    if (this.spec?.coords === "polar") {
      if (name === "pan_axes") return [];
      if (name === "zoom_axes") return ids.filter((axisId) => axisId.startsWith("y"));
    }
    return ids;
  }

  _resetAxisPolicy() {
    if (Array.isArray(this.interaction?.reset_axes)) return this._axisPolicy("reset_axes");
    const axes = [];
    if (this._interactionFlag("pan", true)) axes.push(...this._axisPolicy("pan_axes"));
    if (this._interactionFlag("zoom", true)) axes.push(...this._axisPolicy("zoom_axes"));
    return [...new Set(axes)];
  }

  // An axis zoom can navigate but pan cannot is *contained*: every clamped
  // mutation keeps its window inside its home extents. Cursor-anchored zoom
  // is a scaling plus a translation, so without containment a zoom-in/out
  // chain at two cursor positions is an exact pan of the "locked" axis.
  _axisContained(axisId) {
    if (!this._interactionFlag("navigation", true)) return false;
    if (!this._interactionFlag("zoom", true)) return false;
    if (!this._axisPolicy("zoom_axes").includes(axisId)) return false;
    if (!this._interactionFlag("pan", true)) return true;
    return !this._axisPolicy("pan_axes").includes(axisId);
  }

  _resolveDefaultDragAction() {
    const requested = typeof this.interaction?.default_drag_action === "string"
      ? this.interaction.default_drag_action : "auto";
    const canNavigate = this._interactionFlag("navigation", true);
    const canPan = canNavigate && this._interactionFlag("pan", true)
      && this._axisPolicy("pan_axes").length > 0;
    const canZoom = canNavigate && this._interactionFlag("zoom", true)
      && this._interactionFlag("box_zoom", true);
    const canSelect = this._pickable && this._interactionFlag("select", true)
      && this._interactionFlag("brush", true);
    if (requested === "auto") {
      if (canPan) return "pan";
      if (canZoom) return "zoom";
      if (canSelect) return "select";
      return "none";
    }
    if (requested === "pan") return canPan ? "pan" : this._resolveDefaultDragActionFallback();
    if (requested === "zoom") return canZoom ? "zoom" : this._resolveDefaultDragActionFallback();
    if (requested.startsWith("select")) {
      return canSelect ? requested : this._resolveDefaultDragActionFallback();
    }
    return requested === "none" ? "none" : this._resolveDefaultDragActionFallback();
  }

  _resolveDefaultDragActionFallback() {
    const saved = this.interaction.default_drag_action;
    this.interaction.default_drag_action = "auto";
    const resolved = this._resolveDefaultDragAction();
    this.interaction.default_drag_action = saved;
    return resolved;
  }

  _axisCoord(axis, value) {
    const v = Number(value);
    if (!Number.isFinite(v)) return NaN;
    if (axis && axis.scale === "log") {
      if (v > 0) return Math.log10(v);
      return axis.nonpositive === "mask" ? NaN : -300;
    }
    if (axis && axis.scale === "symlog") {
      const c = Number(axis.constant) || 1;
      return Math.sign(v) * Math.log1p(Math.abs(v) / c);
    }
    return v;
  }

  _axisValue(axis, coord) {
    if (axis && axis.scale === "log") return Math.pow(10, coord);
    if (axis && axis.scale === "symlog") {
      const c = Number(axis.constant) || 1;
      return Math.sign(coord) * c * Math.expm1(Math.abs(coord));
    }
    return coord;
  }

  _axisRange(axisId, view = this.view) {
    const mapped = view?.ranges?.[axisId];
    if (Array.isArray(mapped)) return [mapped[0], mapped[1]];
    if (axisId === "x" && view) return [view.x0, view.x1];
    if (axisId === "y" && view) return [view.y0, view.y1];
    const axis = this._axis(axisId);
    const r = axis.range || [0, 1];
    return [Number(r[0]), Number(r[1])];
  }

  // Stride-thin radial tick LABELS to what the POLAR_RLABEL_DEG spoke can
  // hold. Their usable run is the annulus width projected onto that spoke —
  // about a fifth of the plot at the default 22.5 degrees — so a plot-height
  // worth of labels packed into it and overlapped, the polar path skipping the
  // collision pass that would otherwise thin them. Grid rings come from the
  // same tick list and must keep full density, so only the labels are thinned.
  // Mirrored by _polar_thin_radial_labels in python/xy/_svg.py.
  _polarThinRadialLabels(labels, geom) {
    if (!geom || !Array.isArray(labels)) return labels;
    const span = geom.radius * (1 - (geom.hole || 0));
    const usable = Math.max(1, span * Math.abs(Math.sin((POLAR_RLABEL_DEG * Math.PI) / 180)));
    const capacity = Math.max(2, Math.floor(usable / 45));
    if (labels.length <= capacity) return labels;
    const stride = Math.ceil(labels.length / capacity);
    const thinned = labels.filter((_, i) => i % stride === 0);
    const last = labels[labels.length - 1];
    if (!thinned.includes(last)) thinned.push(last);
    return thinned;
  }

  // One full turn in the axis's own angular unit, or 0 when the axis is not a
  // continuous angular one — mirrors _tick_window_filter in _svg.py.
  _polarAngularTurn(axisId): number {
    const axis = this._axis(axisId);
    if (!axis || !axis.theta_unit || axis.kind === "category") return 0;
    return axis.theta_unit === "degrees" ? 360 : 2 * Math.PI;
  }

  _axisTicks(axisId, target): any {
    const axis = this._axis(axisId);
    let [lo, hi] = this._axisRange(axisId);
    if (this.spec?.coords === "polar" && this._axisDim(axisId) === "x") {
      if (axis.kind === "category") {
        lo = 0;
        hi = Math.max(0, (axis.categories || []).length - 1);
      } else if (Array.isArray(axis.sector) && axis.sector.length === 2) {
        lo = Number(axis.sector[0]);
        hi = Number(axis.sector[1]);
      }
    }
    if (Array.isArray(axis.tick_values)) {
      const a = Math.min(lo, hi), b = Math.max(lo, hi);
      // An angular window can cross the 0/turn seam (sector 300..420, or the
      // compass-natural -30..30). The plain range test drops every tick spelled
      // on the far side of the seam while a data point at that same angle still
      // plots inside the sector, because mark culling is modular. Match it —
      // mirrored by _tick_window_filter in _svg.py.
      const turn = this._polarAngularTurn(axisId);
      const span = b - a;
      const inside = turn
        ? (v) => ((v - a) % turn + turn) % turn <= span + turn * 1e-9
        : (v) => v >= a && v <= b;
      const ticks = axis.tick_values.map(Number).filter((v) => Number.isFinite(v) && inside(v));
      return { ticks, labels: ticks, step: ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) : 1 };
    }
    // Placed after the authored-tick_values return so explicit ticks still
    // win, and before every kind branch — mirrored by axis_ticks in _svg.py.
    if (axis.kind === "category") {
      const categories = axis.categories || [];
      // Every categorical-theta value defines a spoke (and, for
      // grid_shape="linear", one polygon vertex). Cartesian categories may be
      // thinned for legibility, but silently thinning polar categories changes
      // the grid geometry itself. An explicit tick_count remains the opt-in
      // control for authors who want fewer spokes.
      const authoredTarget = Number(axis.tick_count);
      const categoryTarget = this.spec?.coords === "polar"
        && this._axisDim(axisId) === "x"
        && !(Number.isFinite(authoredTarget) && authoredTarget > 0)
        ? categories.length
        : target;
      return categoryTicks(lo, hi, categories, categoryTarget);
    }
    if (axis.theta_unit) return angularTicks(lo, hi, axis.theta_unit, target);
    if (axis.kind === "time") return timeTicks(lo, hi, target);
    if (axis.scale === "log") return logTicks(lo, hi, target);
    if (axis.scale === "symlog") {
      const c0 = this._axisCoord(axis, lo), c1 = this._axisCoord(axis, hi);
      const made = linearTicks(c0, c1, target);
      const ticks = made.ticks.map((v) => this._axisValue(axis, v));
      if (Math.min(lo, hi) <= 0 && Math.max(lo, hi) >= 0 && !ticks.some((v) => Math.abs(v) < 1e-12)) ticks.push(0);
      ticks.sort((a, b) => lo <= hi ? a - b : b - a);
      return { ticks, labels: ticks, step: Math.abs(this._axisValue(axis, made.step)) };
    }
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

  _listen(target, type, handler, options?: any) {
    target.addEventListener(type, handler, options);
    this._listeners.push({ target, type, handler, options });
    return handler;
  }

  // Detach a handler registered through `_listen`. The record carries the live
  // target, so a listener that context-loss recovery re-bound onto a
  // replacement canvas still detaches from the node it ended up on.
  _unlisten(handler) {
    const index = this._listeners.findIndex((record) => record.handler === handler);
    if (index === -1) return;
    const [record] = this._listeners.splice(index, 1);
    record.target.removeEventListener(record.type, record.handler, record.options);
  }

  _captureGesturePointer(owner, event, onLost) {
    const pointerId = event.pointerId;
    let active = true;
    const release = () => {
      if (!active) return;
      active = false;
      this._unlisten(lost);
      // Guarded, so this is a no-op when the browser already took capture back
      // (a real `lostpointercapture`, or the implicit release after pointerup).
      try {
        if (owner.hasPointerCapture(pointerId)) owner.releasePointerCapture(pointerId);
      } catch (_err) { /* synthetic event */ }
    };
    const lost = (lostEvent) => {
      if (!active || lostEvent.pointerId !== pointerId) return;
      release();
      onLost(lostEvent);
    };
    const guard = (moveEvent) => {
      if (!active || moveEvent.pointerId !== pointerId) return false;
      // Pointer capture cannot cross a browsing-context boundary. A mouse
      // released outside an iframe can return without pointerup; treat the
      // first trusted buttonless move as the missing capture-loss signal.
      if (moveEvent.type === "pointermove" && moveEvent.isTrusted
          && moveEvent.pointerType === "mouse" && !(moveEvent.buttons & 1)) {
        lost(moveEvent);
        return false;
      }
      return true;
    };
    this._listen(owner, "lostpointercapture", lost);
    try { owner.setPointerCapture(pointerId); } catch (_err) { /* synthetic event */ }
    return { guard, release };
  }

  _interactionFlag(name, fallback = false) {
    // Rectangle-shaped gestures have no polar geometry yet: a screen-space box
    // neither matches a (theta, r) region nor reads as one. Off rather than
    // half-working, per polar-axes.md §8; hover and radial wheel zoom remain.
    if (
      this.spec?.coords === "polar" &&
      (name === "box_zoom" || name === "select" || name === "brush" || name === "crosshair")
    ) {
      return false;
    }
    const value = this.interaction && this.interaction[name];
    return value === undefined ? fallback : value === true;
  }

  _eventView(source = "view") {
    return {
      ranges: Object.fromEntries(
        this._axisIds().map((axisId) => [axisId, [...this._axisRange(axisId)]])
      ),
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

  _emitViewChange(source = "view", opts: any = {}) {
    if (this._destroyed) return;
    const broadcast = opts.broadcast !== false;
    this._pendingViewEvent = {
      source,
      broadcast,
      axes: Array.isArray(opts.axes) ? [...opts.axes] : [],
      phase: opts.phase || "end",
      interaction_id: opts.interactionId ?? ++this._interactionSeq,
    };
    if (this._viewEventRaf) return;
    this._viewEventRaf = requestAnimationFrame(() => {
      this._viewEventRaf = null;
      const pending = this._pendingViewEvent || { source, broadcast };
      this._pendingViewEvent = null;
      const detail = {
        ...this._eventView(pending.source),
        axes: pending.axes,
        phase: pending.phase,
        interaction_id: pending.interaction_id,
      };
      this._dispatchChartEvent("view_change", detail);
      // End-phase events always ship: they feed the kernel's view_state()
      // cache (view-state.md §5.1) at one message per gesture. Update-phase
      // streams stay gated on listener presence.
      if (this.comm && (pending.phase === "end"
          || !this.comm.wantsViewChange || this.comm.wantsViewChange())) {
        this.comm.send({ type: "view_change", ...detail });
      }
      if (pending.broadcast) this._broadcastLinkedView(detail);
    });
  }

  _initLinkedCharts() {
    const group = this.interaction && this.interaction.link_group;
    if (!group || typeof BroadcastChannel !== "function") return;
    this._linkAxes = this._axisPolicy("link_axes");
    this._linkChannel = new BroadcastChannel(`xy:${group}`);
    this._linkChannel.onmessage = (event) => {
      const msg = event.data || {};
      if (msg.source === this._linkedSource) return;
      if (this._interactionFlag("link_select") && msg.selection) {
        const selection = msg.selection;
        // Linked applies update the durable-state mirror but never push
        // history (view-state.md §4) — dispatch: false already skips it.
        // A linked selection lands in the same overlay state the peer's own
        // gesture would produce: hydrate the persisted overlay (so _drawNow
        // re-projects it) and drop the mutually-exclusive other overlay.
        if (selection.clear) {
          this._clearSelection({ broadcast: false, dispatch: false });
        } else if (selection.polygon) {
          const polygon = selection.polygon.map((point) => [...point]);
          this._clearBoxOverlay();
          this._stateSelection = { polygon: polygon.map((point) => [...point]) };
          this._lassoPolygon = polygon;
          this._selectLocalPolygon(selection.polygon, { dispatch: false });
        } else if (selection.range) {
          const { x0, x1, y0, y1 } = selection.range;
          if ([x0, x1, y0, y1].every(Number.isFinite)) {
            const mode = selection.range.mode === "x" || selection.range.mode === "y"
              ? selection.range.mode : "box";
            this._clearLassoOverlay();
            this._boxSelection = { mode, x0, x1, y0, y1 };
            this._stateSelection = {
              range: mode === "box" ? { x0, x1, y0, y1 } : { x0, x1, y0, y1, mode },
            };
            this._selectLocal(x0, x1, y0, y1, { dispatch: false });
          }
        }
        return;
      }
      if (!msg.view || msg.source === this._linkedSource) return;
      const incoming = msg.view.ranges || {};
      const ranges = Object.fromEntries(
        this._axisIds().map((axisId) => [axisId, [...this._axisRange(axisId)]])
      );
      for (const axisId of this._linkAxes) {
        const range = incoming[axisId]
          || (axisId === "x" ? [msg.view.x0, msg.view.x1] : null)
          || (axisId === "y" ? [msg.view.y0, msg.view.y1] : null);
        if (Array.isArray(range) && range.length === 2 && range.every(Number.isFinite)) {
          ranges[axisId] = [Number(range[0]), Number(range[1])];
        }
      }
      this._setView({ ranges }, {
        animate: false,
        source: "linked",
        phase: "end",
        broadcast: false,
      });
    };
  }

  _broadcastLinkedView(detail) {
    if (!this._linkChannel) return;
    const axes = (detail.axes || []).filter((axisId) => this._linkAxes.includes(axisId));
    if (!axes.length) return;
    const ranges = Object.fromEntries(axes.map((axisId) => [axisId, detail.ranges[axisId]]));
    this._linkChannel.postMessage({
      source: this._linkedSource,
      view: { ...detail, axes, ranges },
    });
  }

  _broadcastLinkedSelection(selection) {
    if (!this._linkChannel || !this._interactionFlag("link_select")) return;
    this._linkChannel.postMessage({ source: this._linkedSource, selection });
  }

  setView(ranges, opts: any = {}) {
    return this._setView({ ranges }, {
      animate: opts.animate === true,
      source: "programmatic",
      phase: "end",
      interactionId: ++this._interactionSeq,
      broadcast: opts.broadcast === true,
    });
  }

  resetView(opts: any = {}) {
    return this._resetView(opts.animate !== false, "reset");
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
    this._queueResize(null, null, true);
  }

  _queueResize(cssW = null, cssH = null, measure = false) {
    if (this._destroyed) return;
    if (cssW || cssH) this._pendingResize = { cssW, cssH };
    if (measure) this._resizeNeedsMeasure = true;
    if (this._resizeRaf) return;
    this._resizeRaf = requestAnimationFrame(() => {
      this._resizeRaf = null;
      let pending = this._pendingResize;
      this._pendingResize = null;
      if (this._resizeNeedsMeasure && this.root) {
        const rect = this.root.getBoundingClientRect();
        if (rect.width || rect.height) pending = { cssW: rect.width, cssH: rect.height };
      }
      this._resizeNeedsMeasure = false;
      if (pending && (pending.cssW || pending.cssH)) {
        this._resize(pending.cssW, pending.cssH);
      }
    });
  }

  _armVisibilityResizeWatch() {
    if (!(this.fluid || this.fluidH)) return;
    const syncSoon = () => {
      if (this._destroyed) return;
      this._syncContainerSize();
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
      // Synchronous on purpose, and pinned that way: `render_smoke_nonumpy.py`'s
      // `dprw` probe calls this and reads `dpr`/`canvas.width`/`chrome.width` on
      // the very next line, because a DPR change with no container resize has no
      // later event to piggyback on. Deferring it into `_queueResize` broke that
      // contract, and the redundant second frame it was meant to save does not
      // exist: the ResizeObserver's queued pass early-returns when width, height
      // and dpr are all unchanged, and when the CSS size *did* change too, the
      // second pass is doing real work at a new size.
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
  _onGlHostContextLost() {
    if (this._destroyed) return;
    clearTimeout(this._glHostRecoveryTimer);
    this._glHostRecoveryTimer = null;
    this._glHostRecoveryDelay = 0;
    // Keep the visible canvas as the per-chart event surface. Existing hosts
    // and telemetry listen here, while the real loss belongs to the detached
    // shared canvas and is fanned out by GLHost.
    this.canvas.dispatchEvent(new Event("webglcontextlost", { cancelable: true }));
  }

  _onGlHostContextRestored() {
    if (this._destroyed) return;
    this.canvas.dispatchEvent(new Event("webglcontextrestored"));
  }

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
      this._ctxLostPending = false; // the loss event has now dispatched
      // Governed releases already stamped "released"; anything else is a
      // browser-side eviction/driver reset (§28: the difference stays legible).
      if (!governedRelease) this.canvas.dataset.xyCtx = "lost";
      // Either way a live context just went away; let peer frames know the
      // shared budget has room (a governed release already announced; this is
      // deduped, and it is what tells peers about a browser-side eviction).
      if (this._governorRegistered) XY_CONTEXT_GOVERNOR._announceLive();
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
      clearTimeout(this._wheelZoomEndTimer);
      this._wheelZoomEndTimer = null;
      this._wheelGesture = null;
      if (this._dataAnimRaf) cancelAnimationFrame(this._dataAnimRaf);
      this._dataAnimRaf = null;
      if (this._dataAnim) {
        this._emitAnimationLifecycle?.("end", this._dataAnim.phase, { cancelled: true });
      }
      this._dataAnim = null;
      this._transitionOldTraces = null; // handles died with the context
      // Preserve the user's zoom/pan across the loss (#156): a backgrounded
      // tab or a scrolled-away chart must come back to where the user left it,
      // not home — the retained spec + payload rebuild the same context, so the
      // settled view is still valid. `this.view` can be a mid-flight
      // interpolation frame, though, so snap any in-progress navigation (view
      // animation or domain transition) to its resting target — the view the
      // user actually settled on — before tearing those animations down.
      // Read the source per-axis through `_axisRange`, which normalizes every
      // view shape (`_transitionView.to` in particular can be a *flat*
      // {x0,x1,y0,y1} from the kernel follow path — feeding that straight to
      // `_copyView`, which only reads `.ranges`, would fall back to each axis's
      // home range and defeat the very preservation this block exists for).
      const settledView = this._viewAnim?.target || this._transitionView?.to || this.view;
      this._transitionView = null;
      this.view = this._copyView({
        ranges: Object.fromEntries(
          this._axisIds().map((axisId) => [axisId, this._axisRange(axisId, settledView)]),
        ),
      });
      this._cancelViewAnimation();
      clearTimeout(this._viewTimer);
      this._viewTimer = null;
      clearTimeout(this._rebinTimer);
      this._rebinTimer = null;
      this._viewRequestBurstStart = null;
      this._dispatchChartEvent("context_lost", {
        loss_count: this._contextLossCount,
      });
      // The host owns restoration of the one real context and will fan the
      // restored event back out to every surviving client. Rebuilding or
      // replacing this 2D presentation canvas cannot restore that context.
      if (this._glHost) return;
      // A governed release keeps a snapshot and deliberately waits until the
      // chart is requested again. A browser-side eviction is different: the
      // canvas has no stand-in, and IntersectionObserver may not deliver a
      // new entry when an already-visible chart loses its context (notably
      // when other chart-heavy tabs push Chrome over its process-wide cap).
      // Rebuild on the next task while this document is active so the loss
      // handler can finish first and the visible chart never waits for a
      // scroll-out/scroll-in cycle to recover.
      const documentVisible =
        typeof document === "undefined" ||
        !document.visibilityState ||
        document.visibilityState === "visible";
      if (!governedRelease && this._ctxVisible && documentVisible) {
        setTimeout(() => {
          if (
            !this._destroyed &&
            this._glLost &&
            this.canvas.dataset.xyCtx === "lost" &&
            this._ctxVisible
          ) {
            this._recoverContext();
          }
        }, 0);
      }
      // A governed release whose re-acquire raced ahead of this event deferred
      // its restoreContext() (see _recoverContext). Schedule the retry on the
      // next task rather than calling it here: restoreContext() invoked
      // synchronously inside the webglcontextlost dispatch is also ignored by
      // Chromium — it must run after the loss event fully unwinds.
      if (governedRelease && this._ctxRecoverRequested && !this._destroyed && this._ctxVisible) {
        this._ctxRecoverRequested = false;
        setTimeout(() => {
          if (!this._destroyed && this._glLost && this._ctxVisible) this._recoverContext();
        }, 0);
      }
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
        this._glLost = false;
        // Compile the programs this chart actually uses and submit a complete
        // frame before advertising the replacement context as live. Under
        // process-wide pressure Chrome can lose a just-created context during
        // resource setup; an async draw would otherwise leave a blank canvas
        // stamped "live" and surface a later `shader compile: null` from pick.
        this._drawNow();
        this._assertContextFrameReady("restore");
      } catch (err) {
        this._glLost = true;
        this.canvas.dataset.xyCtx = "lost";
        this.root.dataset.xyContextState = "lost";
        // A null shader log is Chromium's characteristic response when the
        // context disappears mid-compile. Keep the chart recoverable instead
        // of turning transient global pressure into a permanent error card.
        const transient =
          !this.gl ||
          this.gl.isContextLost() ||
          String(err && err.message || err).includes("shader compile: null") ||
          String(err && err.message || err).startsWith("WebGL error ");
        if (transient) {
          this._contextRecoveryError = null;
          if (this._glHost) {
            if (this.gl && !this.gl.isContextLost()) {
              try { this._destroyGlResources(); } catch (_cleanupError) {}
            }
            this._scheduleGlHostClientRecovery();
          } else {
            this._scheduleContextRecovery();
          }
          return;
        }
        this._contextRecoveryError = err;
        clearTimeout(this._glHostRecoveryTimer);
        this._glHostRecoveryTimer = null;
        this._glHostRecoveryDelay = 0;
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
      this._contextRestoreCount += 1;
      this._contextRecoveryError = null;
      this._ctxRecoveryDelay = 0;
      clearTimeout(this._glHostRecoveryTimer);
      this._glHostRecoveryTimer = null;
      this._glHostRecoveryDelay = 0;
      this.canvas.dataset.xyCtx = "live";
      this.root.dataset.xyContextState = "ready";
      if (this._governorRegistered) {
        XY_CONTEXT_GOVERNOR._announceLive(); // fallback context recovered; peers rebalance
      }
      this._scheduleViewRequest(this.view, { delay: 0 });
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
    if (this._glHost) return false;
    if (this._destroyed || !this.gl || this._glLost || this.gl.isContextLost()) return false;
    const ext = this.gl.getExtension("WEBGL_lose_context");
    if (!ext) return false;
    this._snapshotBeforeRelease();
    this._ctxReleasedExt = ext;
    this._ctxReleases += 1;
    this._glLost = true; // synchronous: the lost *event* arrives as a task
    this._ctxLostPending = true; // ...and restoreContext() must wait for it
    this.canvas.dataset.xyCtx = "released";
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
    ext.loseContext();
    XY_CONTEXT_GOVERNOR._announceLive(); // one fewer live context on this frame
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
      // Do not copy the default WebGL framebuffer with drawImage(). Contexts
      // use preserveDrawingBuffer=false, so Chrome may hand the 2D canvas an
      // already-discarded transparent buffer even though _drawNow() just
      // submitted the marks. Read the freshly drawn pixels synchronously
      // before WEBGL_lose_context instead; this keeps governed releases from
      // showing only the independently painted grid/chrome while scrolling a
      // many-chart page.
      const gl = this.gl;
      const w = this.canvas.width;
      const h = this.canvas.height;
      gl.finish();
      const pixels = new Uint8Array(w * h * 4);
      gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      const ctx = snap.getContext("2d");
      const image = ctx.createImageData(w, h);
      const data = image.data;
      // Flip WebGL's bottom-up rows while converting its premultiplied colors
      // to the straight-alpha channels expected by ImageData. Keeping both
      // transforms in one pixel pass avoids scanning every snapshot twice.
      for (let srcY = 0; srcY < h; srcY++) {
        let src = srcY * w * 4;
        const srcEnd = src + w * 4;
        let dst = (h - 1 - srcY) * w * 4;
        for (; src < srcEnd; src += 4, dst += 4) {
          const alpha = pixels[src + 3];
          let red = pixels[src];
          let green = pixels[src + 1];
          let blue = pixels[src + 2];
          if (alpha > 0 && alpha < 255) {
            const scale = 255 / alpha;
            red = Math.min(255, Math.round(red * scale));
            green = Math.min(255, Math.round(green * scale));
            blue = Math.min(255, Math.round(blue * scale));
          }
          data[dst] = red;
          data[dst + 1] = green;
          data[dst + 2] = blue;
          data[dst + 3] = alpha;
        }
      }
      ctx.putImageData(image, 0, 0);
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
    if (this._glHost) {
      // Host-wide recovery fans out its own restored event. This path handles
      // a client-only rebuild that was deferred while its view or document
      // was hidden after a transient allocation failure.
      this._scheduleGlHostClientRecovery();
      return;
    }
    // Governed release, but its webglcontextlost event has not dispatched yet
    // (scrolled back into view in the same task it was released). Chromium
    // drops a restoreContext() issued before the loss event, stranding the
    // context lost forever — so defer; the loss handler re-invokes us once the
    // event lands (and restoreContext is then honored).
    if (this._ctxReleasedExt && this._ctxLostPending) {
      this._ctxRecoverRequested = true;
      return;
    }
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

  _assertContextFrameReady(stage) {
    if (!this.gl) {
      throw new Error(`context lost during ${stage} draw`);
    }
    // This runs only during recovery. Paying for a synchronous completion
    // here prevents command-queue acceptance from being mistaken for a real
    // frame when Chrome revokes the new context under global pressure.
    this.gl.finish();
    if (this.gl.isContextLost()) throw new Error(`context lost during ${stage} draw`);
    // WebGL resource creation can fail under process-wide pressure without a
    // useful shader log. A clean first frame is the commit point: do not call
    // the canvas live while setup/draw left an error behind.
    const error = this.gl.getError();
    if (error !== this.gl.NO_ERROR) {
      throw new Error(`WebGL error ${error} during ${stage} draw`);
    }
  }

  _scheduleContextRecovery() {
    if (this._ctxRecoveryTimer || this._destroyed || !this._ctxVisible) return;
    if (
      typeof document !== "undefined" &&
      document.visibilityState &&
      document.visibilityState !== "visible"
    ) return;
    const delay = this._ctxRecoveryDelay || 50;
    this._ctxRecoveryDelay = Math.min(1000, delay * 2);
    this._ctxRecoveryTimer = setTimeout(() => {
      this._ctxRecoveryTimer = null;
      if (this._glLost && !this._destroyed && this._ctxVisible) this._recoverContext();
    }, delay);
  }

  // A host can be healthy while one client fails transiently during its own
  // shader/buffer rebuild. Retry that client without letting a hidden or
  // off-screen chart spin at frame rate under persistent GPU pressure.
  _scheduleGlHostClientRecovery() {
    if (
      this._glHostRecoveryTimer ||
      this._destroyed ||
      !this._glHost ||
      !this._glLost ||
      !this._ctxVisible
    ) return;
    if (
      typeof document !== "undefined" &&
      document.visibilityState &&
      document.visibilityState !== "visible"
    ) return;
    const delay = this._glHostRecoveryDelay || 50;
    this._glHostRecoveryDelay = Math.min(1000, delay * 2);
    const host = this._glHost;
    this._glHostRecoveryTimer = setTimeout(() => {
      this._glHostRecoveryTimer = null;
      if (
        this._destroyed ||
        this._glHost !== host ||
        !this._glLost ||
        !this._ctxVisible ||
        !host.ready ||
        host.lost ||
        !host.gl ||
        host.gl.isContextLost() ||
        (
          typeof document !== "undefined" &&
          document.visibilityState &&
          document.visibilityState !== "visible"
        )
      ) return;
      this._onGlHostContextRestored();
    }, delay);
  }

  _rebuildEvictedContext() {
    // The evicted context object is dead for good and a canvas keeps its
    // context forever, so recovery swaps in a fresh canvas (attributes
    // cloned, listeners retargeted) and rebuilds — the same §18/§27 rebuild
    // the restored path uses.
    // A transactional restore can also reject a technically-live context
    // whose first frame reported an error. Explicitly release that stale
    // handle before replacing the canvas so retries do not add to the global
    // pressure they are trying to escape.
    if (this.gl && !this.gl.isContextLost()) {
      try { this.gl.getExtension("WEBGL_lose_context")?.loseContext(); } catch (_err) {}
    }
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
      this._glLost = false;
      this._drawNow();
      this._assertContextFrameReady("rebuild");
    } catch (_err) {
      this._glLost = true;
      this.canvas.dataset.xyCtx = "lost";
      this._scheduleContextRecovery();
      return; // context pressure persists; the next visibility pass retries
    }
    this._ctxRecoveryDelay = 0;
    this.canvas.dataset.xyCtx = "live";
    XY_CONTEXT_GOVERNOR._announceLive(); // rebuilt on a fresh canvas; peers rebalance
    this._scheduleViewRequest(this.view, { delay: 0 });
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
    // A background tab can lose contexts without changing any element's
    // intersection state. When the tab becomes active again, eagerly recover
    // an on-screen browser-evicted canvas; governed releases still retain
    // their snapshots and stay demand-driven.
    if (typeof document !== "undefined") {
      this._listen(document, "visibilitychange", () => {
        if (document.visibilityState === "hidden") {
          // Chrome's WebGL allowance is process-wide in the multi-tab case.
          // Release healthy contexts from the inactive document without doing
          // every synchronous snapshot inside this visibilitychange turn.
          XY_CONTEXT_GOVERNOR.scheduleHiddenReleases();
          return;
        }
        XY_CONTEXT_GOVERNOR.cancelHiddenReleases();
        if (
          document.visibilityState === "visible" &&
          this._ctxVisible &&
          this._glLost &&
          !this._destroyed
        ) {
          this._recoverContext();
        }
      });
    }
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
        } else if (!this._destroyed) {
          // Now off-screen and releasable: if a sibling frame has pushed the
          // shared budget over, give this context back rather than waiting for
          // the browser to evict some other frame's visible chart.
          XY_CONTEXT_GOVERNOR._rebalance();
        }
      },
      { rootMargin: "25% 0px 25% 0px" },
    );
    this._ctxIo.observe(this.root);
  }

  // Re-upload the buffers whose values were baked at a device-pixel ratio, after
  // dpr changed under them (browser zoom, or a window moving between displays).
  //
  // Per-instance stroke/line widths (`styleBuf` component 2) and corner radii
  // (`radiusBuf`) are written in DEVICE pixels at build time, because the
  // shaders consume device pixels. Everything else in the frame absorbs a dpr
  // change through uniforms and the backing-store resize, so these two silently
  // kept the OLD scale: after a zoom from 1x to 2x, a chart's authored 2 px
  // strokes and 6 px wedge corners rendered at half their intended size, and
  // only these marks were wrong. The streaming-append fast path already refuses
  // to patch a trace whose `_styleDpr` is stale (54_kernel.ts); this is the
  // matching repair for the traces already on the GPU.
  _rescaleDprBakedBuffers() {
    if (!this.gl || this._glLost) return;
    const dpr = this.dpr;
    const rescale = (record) => {
      if (!record) return;
      const previous = Number(record._styleDpr);
      if (!(previous > 0) || previous === dpr) return;
      // Repair in place ONLY while the CPU mirrors still cover every row the
      // GPU holds. The streaming-append fast path extends styleBuf with a tail
      // `bufferSubData` and advances `n` without growing `_cpuStyle`
      // (54_kernel.ts), so after an append the mirror is short: re-uploading it
      // would shrink the store out from under the appended rows, and scaling it
      // would leave that tail at the old dpr either way. Leave `_styleDpr`
      // stale instead — the append guard then refuses the fast path and its
      // rebuild renormalizes every row at the current dpr, which is the
      // fallback that case has always relied on.
      const rows = Number(record.n);
      if (!(rows > 0)) return;
      if (record._cpuStyle && record._cpuStyle.length !== rows * 4) return;
      if (record._cpuRadius && record._cpuRadius.length !== rows * 2) return;
      const factor = dpr / previous;
      // Widths ride component 2 of the canonical style row; the other three
      // components (opacity, artist alpha, symbol) are dpr-independent.
      const style = record._cpuStyle;
      if (style && record.styleBuf) {
        for (let i = 2; i < style.length; i += 4) style[i] *= factor;
        this._reuploadBuffer(record.styleBuf, style);
      }
      const radius = record._cpuRadius;
      if (radius && record.radiusBuf) {
        for (let i = 0; i < radius.length; i++) radius[i] *= factor;
        this._reuploadBuffer(record.radiusBuf, radius);
      }
      record._styleDpr = dpr;
    };
    for (const g of this.gpuTraces || []) {
      rescale(g);
      rescale(g.drill);
      rescale(g.sampleOverlay);
      for (const d of g.densityCache || []) rescale(d && d.overlay);
      rescale(g.density && g.density.overlay);
    }
    for (const g of this._transitionOldTraces || []) rescale(g);
  }

  _reuploadBuffer(buffer, data) {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
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
    // Before the layout/paint below, so this frame draws at the new scale.
    this._rescaleDprBakedBuffers();
    this._layout();
    const p = this.plot;
    // Legends are bounded by the box they place in, which under polar is the
    // reserved gutter rather than the plot rect — clamping to the plot would let
    // a long label spill back over the disc the gutter exists to protect.
    const lb = this._legendRect || p;
    this.root.style.setProperty("--xy-legend-max-width", Math.max(40, lb.w - 12) + "px");
    this.root.style.setProperty("--xy-legend-max-height", Math.max(40, lb.h - 12) + "px");
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
      const anchor = lg.dataset.xyLegendAnchor ? JSON.parse(lg.dataset.xyLegendAnchor) : null;
      this._positionLegend(lg, lg.dataset.xyLegendLoc || "upper right", anchor);
    }
    this._positionTitles();
    this._positionReductionBadges();
    this._positionColorbar();
    this._fitModebar();
    this._layoutAxisBands();
    this._pickDirty = true;
    // Changing a canvas backing-store dimension clears it immediately. Resize
    // work is already coalesced into one animation frame, so paint in that same
    // frame instead of exposing cleared canvases until a second rAF callback.
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
    this._drawNow();
    this._scheduleViewRequest();
  }

  _buildDom(el) {
    const s = this.spec;
    const root = document.createElement("div");
    root.className = "xy";
    root.style.cssText =
      `position:relative;width:${this.fluid ? "100%" : this.size.w + "px"};` +
      `height:${this.fluidH ? "100%" : this.size.h + "px"};` +
      `--xy-legend-max-width:${Math.max(40, (this._legendRect || this.plot).w - 12)}px;` +
      `--xy-legend-max-height:${Math.max(40, (this._legendRect || this.plot).h - 12)}px;` +
      (this.fluidH ? "min-height:120px;" : "") + // parent without a height -> visible floor
      "user-select:none;";
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
    const titleText = this._titleEntries().map((entry) => String(entry.text)).join(". ");
    root.setAttribute("aria-label", titleText ? `Chart: ${titleText}` : "Interactive chart");
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

    this._titleElements = [];
    for (const entry of this._titleEntries()) {
      const t = document.createElement("div");
      t.textContent = entry.text;
      t.style.cssText =
        "position:absolute;white-space:pre-line;line-height:1.2;";
      this._applySlot(t, "title");
      for (const [property, value] of Object.entries(entry.style || {})) {
        if (["color", "font-family", "font-size", "font-style", "font-weight"].includes(property)) {
          t.style.setProperty(property, String(value));
        }
      }
      root.appendChild(t);
      this._titleElements.push({ element: t, entry });
    }
    this._positionTitles();

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
    this._applySlot(this.overlay, "annotation_layer");
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
    const titles = this._titleEntries().map((entry) => String(entry.text));
    const parts = [titles.length ? `${titles.join(". ")}.` : "Interactive chart."];
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
      if (entry._legendHidden) continue; // hidden series badge nothing
      if (t.tier !== "density" || !t.density) continue;
      // Badge what is actually drawn: the overlay _drawDensitySample chose
      // for the current view (T9 pairing). Before the first frame runs, the
      // home overlay (or the spec's sample counts) stands in.
      const shown = entry._shownSampleOverlay || entry.sampleOverlay;
      const sample = shown && shown.sample ? shown.sample : t.density.sample;
      if (sample && Number(sample.n) > 0 && !entry._sampleFadedOut) {
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
    // A chrome rebuild replaces the row nodes mid-hover, so their pointerleave
    // never fires; release any active dim state before dropping the old boxes.
    this._clearLegendHover();
    this._legends = [];
    // Toggle state survives chrome/GPU rebuilds: it lives on the view keyed
    // by spec-trace index, and freshly built rows re-adopt it below.
    this._legendOffTraces = this._legendOffTraces || new Set();
    this._legendOffCats = this._legendOffCats || new Map();
    const items = [];
    if (s.show_legend !== false) {
      const explicit = (s.legend && s.legend.items) || [];
      if (explicit.length) {
        for (const it of explicit) {
          items.push({
            swatch: it.style && it.style.color,
            name: it.name,
            symbol: it.kind === "scatter" ? (it.style?.symbol || "circle") : null,
            line: ["line", "segments", "step", "stairs", "errorbar"].includes(it.kind),
            style: it.style || {},
          });
        }
      } else {
        // Two identically-encoded unnamed continuous traces must not stack two
        // identical gradient rows; the row is about the encoding, so later
        // traces join the first row's hover-target list instead.
        const continuousRows = new Map();
        s.traces.forEach((t, ti) => {
          const style = { ...(t.style || {}) };
          const useTraceSize = style._legend_trace_size === true;
          delete style._legend_trace_size;
          if (t.kind === "scatter" && useTraceSize &&
              t.size?.mode === "constant" && Number.isFinite(Number(t.size.size))) {
            style.size = Number(t.size.size);
          }
          // A density-tier surface encodes count as alpha and wears the mean
          // point color (LOD doc §2), so it gets no colormap gradient swatch —
          // a gradient would claim color == density. A named density trace
          // falls through to the plain marker swatch below, matching the
          // static SVG/raster exporters.
          const line = ["line", "segments", "step", "stairs", "errorbar"].includes(t.kind);
          if (t.color && t.color.mode === "categorical") {
            t.color.categories.forEach((cat, i) =>
              items.push({ swatch: t.color.palette[i], name: cat, symbol: t.kind === "scatter" ? (style.symbol || "circle") : null, style, traces: [ti], cat: i }));
          } else if (t.color && t.color.mode === "continuous") {
            // Label precedence: explicit series name, then the encoding's own
            // declarative label (the color="column" idiom). No generic fallback:
            // an unnamed encoding has nothing truthful to say, so it gets no
            // row — matching the static exporters, which draw name-bearing
            // entries only.
            const name = t.name || t.color.label;
            if (!name) return;
            const key = name + "\u0000" + colormapKey(t.color.colormap);
            const existing = continuousRows.get(key);
            if (existing) {
              existing.traces.push(ti);
              return;
            }
            const item = { swatch: "gradient", cmap: t.color.colormap, name, symbol: t.kind === "scatter" ? (style.symbol || "circle") : null, line, style, traces: [ti] };
            continuousRows.set(key, item);
            items.push(item);
          } else if (t.name) {
            const c = (t.color && t.color.color) || (t.style && t.style.color);
            // Line-family kinds get a short line sample (honoring the dash), the
            // same handle the raster/SVG exporters draw — not a filled swatch.
            items.push({ swatch: c, name: t.name, symbol: t.kind === "scatter" ? (style.symbol || "circle") : null, line, style, traces: [ti] });
          }
        });
      }
      for (const it of items) {
        if (!it.traces) continue;
        it.off = it.cat != null
          ? !!this._legendOffCats.get(it.traces[0])?.has(it.cat)
          : it.traces.every((ti) => this._legendOffTraces.has(ti));
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
    const lg: any = document.createElement("div");
    const loc = options.loc || "upper right";
    const ncols = Math.max(1, Number(options.ncols) || 1);
    const horizontal = ncols > 1;
    const handleHeight = options.handleheight == null
      ? null
      : Math.max(8, 11 * Number(options.handleheight));
    const handleLength = Number.isFinite(Number(options.handlelength))
      ? Math.max(0, Number(options.handlelength))
      : 2;
    const handleTextPad = Number.isFinite(Number(options.handletextpad))
      ? Math.max(0, Number(options.handletextpad))
      : 0.8;
    // `minmax(0, max-content)`, not bare `max-content`: the box is capped at
    // `--xy-legend-max-width`, and a column that refuses to shrink below its
    // content made a long row overflow horizontally — a legend with a horizontal
    // SCROLLBAR, which hides the label it is meant to be showing. Shrinkable
    // columns let a long label WRAP inside its column instead, so the inline axis
    // never needs to scroll and the text stays whole; the block axis still
    // scrolls, which is the browser legend's advantage over the static
    // exporters, which can only ellipsize. Row `title`/ARIA carries the full
    // name either way, for the rows the block-axis cap does clip.
    lg.style.cssText = "position:absolute;" +
      `display:grid;grid-template-columns:repeat(${horizontal ? ncols : 1},minmax(0,max-content));` +
      "column-gap:2em;row-gap:.5em;overflow-x:hidden;overflow-y:auto;";
    lg.dataset.xyLegendLoc = loc;
    if (Array.isArray(options.anchor)) {
      lg.dataset.xyLegendAnchor = JSON.stringify(options.anchor);
    }
    if (Number.isFinite(Number(options.border_pad))) {
      lg.dataset.xyLegendBorderPad = String(Math.max(0, Number(options.border_pad)));
    }
    this._positionLegend(lg, loc, options.anchor);
    this._applySlot(lg, "legend");
    this._applyStyle(lg, options.style);
    if (options.title) {
      const title = document.createElement("div");
      title.textContent = String(options.title);
      title.style.gridColumn = `1 / span ${horizontal ? ncols : 1}`;
      this._applySlot(title, "legend_title");
      lg.appendChild(title);
    }
    const rows = [];
    for (const it of items) {
      const row = document.createElement("div");
      this._applySlot(row, "legend_item");
      if (handleHeight != null) row.style.minHeight = `${handleHeight + 2}px`;
      const sw = document.createElement("span");
      // Renderer-owned paint/geometry feed private variables consumed by the
      // base-layer slot rule. SVG paint lives on the wrapper and inherits into
      // its path/line, so Tailwind fill-*/stroke-* utilities on this public slot
      // can override it without copying layout classes onto SVG paint nodes.
      sw.style.setProperty("--xy-legend-swatch-width", `${handleLength}em`);
      sw.style.setProperty("--xy-legend-swatch-margin-right", `${handleTextPad}em`);
      let bg = it.swatch;
      // A continuous encoding paints the swatch with the colormap ramp, but
      // the swatch keeps the mark's identity: a gradient-filled symbol for
      // scatters, a gradient-stroked line sample for line-family kinds, and
      // only the bare ramp chip when the mark has neither.
      let gradientPaint = null;
      if (it.swatch === "gradient" && (it.symbol || it.line)) {
        gradientPaint = (svg) => this._legendGradientPaint(svg, it.cmap);
      } else if (it.swatch === "gradient") {
        const stops = colormapStops(it.cmap);
        bg = `linear-gradient(90deg,${stops.map((c) => `rgb(${c[0]},${c[1]},${c[2]})`).join(",")})`;
        sw.style.setProperty("--xy-legend-swatch-paint", bg);
      }
      if (it.symbol) {
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", "0 0 18 14");
        svg.setAttribute("width", "100%");
        svg.setAttribute("height", "14");
        svg.style.overflow = "visible";
        const color = gradientPaint ? gradientPaint(svg) : safeCssPaint(this.root, bg);
        this._appendLegendMarker(
          svg, sw, { ...(it.style || {}), symbol: it.symbol }, color, 9, 7, true,
        );
        sw.appendChild(svg);
        sw.style.setProperty("--xy-legend-swatch-height", "14px");
      } else if (it.line) {
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", "0 0 22 12");
        svg.setAttribute("width", "100%");
        svg.setAttribute("height", "12");
        const ln = document.createElementNS(ns, "line");
        ln.setAttribute("x1", "1");
        ln.setAttribute("y1", "6");
        ln.setAttribute("x2", "21");
        ln.setAttribute("y2", "6");
        const lineColor = gradientPaint
          ? gradientPaint(svg)
          : safeCssPaint(this.root, bg);
        if (it.style?.legend_gap_color && it.style?.dash?.length) {
          const gaps = document.createElementNS(ns, "line");
          gaps.setAttribute("x1", "1");
          gaps.setAttribute("y1", "6");
          gaps.setAttribute("x2", "21");
          gaps.setAttribute("y2", "6");
          gaps.setAttribute(
            "stroke",
            safeCssPaint(this.root, it.style.legend_gap_color),
          );
          gaps.setAttribute("stroke-width", String(it.style?.width ?? 1.5));
          gaps.setAttribute("stroke-dasharray", "none");
          svg.appendChild(gaps);
        }
        sw.style.setProperty("--xy-legend-swatch-fill", "none");
        sw.style.setProperty(
          "--xy-legend-swatch-stroke",
          lineColor,
        );
        // ?? not ||: an explicit lw=0 keeps 0 and draws nothing, like the
        // exporters' dict-default and Matplotlib itself.
        sw.style.setProperty(
          "--xy-legend-swatch-stroke-width",
          String(it.style?.width ?? 1.5),
        );
        if (it.style?.dash && it.style.dash.length) {
          sw.style.setProperty("--xy-legend-swatch-dasharray", it.style.dash.join(" "));
        }
        svg.appendChild(ln);
        if (it.style?.legend_marker) {
          this._appendLegendMarker(
            svg, sw, it.style.legend_marker, lineColor, 11, 6, false,
          );
        }
        sw.appendChild(svg);
        sw.style.setProperty("--xy-legend-swatch-height", "12px");
      } else if (it.swatch !== "gradient") {
        // Keep the dynamic base paint on the security-audited safe sink, but
        // expose it through the private variable consumed by the base-layer
        // slot rule so Tailwind background utilities can still override it.
        sw.style.setProperty(
          "--xy-legend-swatch-paint",
          safeCssPaint(this.root, bg),
        );
        const strokeWidth = Number(it.style?.stroke_width) || 0;
        if (it.style?.stroke && strokeWidth > 0) {
          sw.style.boxSizing = "border-box";
          sw.style.borderStyle = "solid";
          sw.style.borderWidth = `${strokeWidth}px`;
          sw.style.borderColor = safeCssPaint(this.root, it.style.stroke);
        }
        // Hatch layers are explicit mark semantics and sit over that sanitized
        // base paint without forcing the base color into an inline background.
        if (it.style?.hatch) {
          const hatchColor = safeCssPaint(this.root, it.style.hatch_color || "#222222");
          const patterns = [];
          const hatch = String(it.style.hatch);
          if (hatch.includes("/") || hatch.includes("*"))
            patterns.push(`repeating-linear-gradient(135deg,transparent 0 4px,${hatchColor} 4px 5px)`);
          if (hatch.includes("\\") || hatch.includes("*"))
            patterns.push(`repeating-linear-gradient(45deg,transparent 0 4px,${hatchColor} 4px 5px)`);
          if (hatch.includes("-"))
            patterns.push(`repeating-linear-gradient(0deg,transparent 0 4px,${hatchColor} 4px 5px)`);
          if (hatch.includes("."))
            patterns.push(`radial-gradient(circle,${hatchColor} 1px,transparent 1px)`);
          sw.style.backgroundImage = patterns.join(",");
          if (hatch.includes(".")) sw.style.backgroundSize = "5px 5px";
        }
        if (handleHeight != null) {
          sw.style.setProperty("--xy-legend-swatch-height", `${handleHeight}px`);
        }
      }
      this._applySlot(sw, "legend_swatch");
      row.appendChild(sw);
      const label = document.createElement("span");
      label.textContent = it.name;
      this._applySlot(label, "legend_label");
      row.appendChild(label);
      // A row too wide for the capped box ellipsizes (the `legend_item` /
      // `legend_label` rules in 20_theme.ts) rather than pushing a horizontal
      // scrollbar onto the legend. Only the LABEL clips: the swatch is
      // `flex:none` and keeps `overflow:visible`, so an authored oversized
      // marker still draws outside its 18x14 box. Same full-text-in-title/ARIA
      // rule categorical tick labels use, so nothing an ellipsis hides becomes
      // unreachable.
      if (it.name) {
        row.title = String(it.name);
        row.setAttribute("aria-label", String(it.name));
      }
      // Hover emphasis (interaction spec §9): rows backed by live traces dim the rest
      // of the chart while hovered. Manually-added Legend artists carry no
      // trace linkage, so extra_legends rows stay inert.
      if (options.highlight !== false && it.traces && it.traces.length) {
        row.addEventListener("pointerenter", () => this._setLegendHover(it, lg, row));
        row.addEventListener("pointerleave", () => this._clearLegendHover());
      }
      // Click-to-toggle (interaction spec §10): hide/show what the row
      // stands for. Same trace-linkage rule keeps extra_legends rows inert.
      if (options.toggle !== false && it.traces && it.traces.length) {
        row.style.cursor = "pointer";
        row.addEventListener("click", () => this._legendToggle(it, row));
      }
      this._syncLegendRow(row, it);
      rows.push({ row, it });
      lg.appendChild(row);
    }
    lg._xyItemRows = rows;
    root.appendChild(lg);
    this._legends.push(lg); // _resize refreshes each box's responsive anchor
    return lg;
  }

  _appendLegendMarker(svg, sw, marker, defaultColor, cx, cy, wrapperPaint) {
    const ns = "http://www.w3.org/2000/svg";
    const requestedMarkerSize = Number(marker?.size);
    const hasMarkerSize = Number.isFinite(requestedMarkerSize) && requestedMarkerSize >= 0;
    const markerSize = hasMarkerSize ? requestedMarkerSize : 9;
    const symbol = String(marker?.symbol || "circle");
    // The generated default can be an internal SVG url(...); sanitize only
    // user-authored paints so the gradient reference remains intact.
    const fillColor = marker?.color != null
      ? safeCssPaint(this.root, marker.color)
      : defaultColor;
    const hasStroke = marker?.stroke != null || marker?.stroke_width != null;
    const strokeColor = hasStroke
      ? (marker?.stroke != null
          ? safeCssPaint(this.root, marker.stroke)
          : fillColor)
      : (wrapperPaint ? fillColor : "none");
    const paths = {
      square: "M4.5 2.5h9v9h-9z", diamond: "M9 2l5 5-5 5-5-5z",
      thin_diamond: "M9 2l3 5-3 5-3-5z",
      triangle: "M9 2l-5 10h10z", triangle_down: "M9 12L4 2h10z",
      triangle_left: "M4 7L14 2v10z", triangle_right: "M14 7L4 2v10z",
      plus_line: "M9 2v10M4 7h10", x_line: "M5 3l8 8M13 3l-8 8",
      horizontal_line: "M4 7h10", vertical_line: "M9 2v10",
      cross: "M7.5 2h3v3.5H14v3h-3.5V12h-3V8.5H4v-3h3.5z",
      x: "M5.5 2L9 5.5 12.5 2 14 3.5 10.5 7 14 10.5 12.5 12 9 8.5 5.5 12 4 10.5 7.5 7 4 3.5z",
      pentagon: "M9 2.5L13.28 5.61 11.65 10.64H6.35L4.72 5.61z",
      hexagon: "M9 2L13.3 4.5v5L9 12l-4.3-2.5v-5z",
      star: "M9 2l1.5 3.1 3.5.5-2.5 2.5.6 3.5L9 10l-3.1 1.6.6-3.5L4 5.6l3.5-.5z"
    };
    if (marker?.marker_glyph) {
      const text = document.createElementNS(ns, "text");
      text.setAttribute("x", String(cx));
      text.setAttribute("y", String(cy));
      text.setAttribute("font-family", "DejaVu Sans");
      text.setAttribute("font-size", String(markerSize));
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("dominant-baseline", "central");
      if (wrapperPaint) {
        sw.style.setProperty("--xy-legend-swatch-fill", fillColor);
        sw.style.setProperty("--xy-legend-swatch-stroke", "none");
        sw.style.setProperty("--xy-legend-swatch-stroke-width", "0");
      } else {
        text.setAttribute("fill", fillColor);
      }
      text.textContent = String(marker.marker_glyph);
      svg.appendChild(text);
      return;
    }
    const path = document.createElementNS(ns, "path");
    if (marker?.marker_path) {
      const commands = [];
      for (const contour of marker.marker_path.contours || []) {
        for (let offset = 0; offset + 1 < contour.length; offset += 2) {
          const x = cx + markerSize * Number(contour[offset]);
          const y = cy - markerSize * Number(contour[offset + 1]);
          commands.push(`${offset === 0 ? "M" : "L"}${x} ${y}`);
        }
        if (marker.marker_path.filled) commands.push("Z");
      }
      path.setAttribute("d", commands.join(" "));
    } else if (symbol === "circle" || symbol === "point" || symbol === "pixel") {
      const radius = markerSize / 2;
      if (symbol === "pixel")
        path.setAttribute("d", `M${cx - radius} ${cy - radius}h${markerSize}v${markerSize}h-${markerSize}z`);
      else
        path.setAttribute("d", `M${cx} ${cy - radius}a${radius} ${radius} 0 1 0 0 ${markerSize}a${radius} ${radius} 0 1 0 0 -${markerSize}`);
    } else {
      path.setAttribute("d", paths[symbol] || paths.square);
      const scale = hasMarkerSize ? markerSize / 9 : 1;
      path.setAttribute(
        "transform",
        `translate(${cx} ${cy}) scale(${scale}) translate(-9 -7)`,
      );
    }
    const lineMarker = symbol.endsWith("_line") ||
      (marker?.marker_path && !marker.marker_path.filled);
    const fill = lineMarker ? "none" : fillColor;
    const requestedStrokeWidth = Number(marker?.stroke_width);
    const strokeWidth = Number.isFinite(requestedStrokeWidth)
      ? requestedStrokeWidth
      : (wrapperPaint ? 1 : 0);
    if (wrapperPaint) {
      sw.style.setProperty("--xy-legend-swatch-fill", fill);
      sw.style.setProperty("--xy-legend-swatch-stroke", strokeColor);
      sw.style.setProperty("--xy-legend-swatch-stroke-width", String(strokeWidth));
    } else {
      path.setAttribute("fill", fill);
      path.setAttribute("stroke", strokeColor);
      path.setAttribute("stroke-width", String(strokeWidth));
      path.setAttribute("stroke-dasharray", "none");
    }
    svg.appendChild(path);
  }

  // Paint an SVG swatch with the item's colormap ramp: registers a
  // <linearGradient> in the swatch's own defs and returns its paint URL.
  // IDs are document-global, so a module counter keeps multiple charts on
  // one page from cross-referencing each other's ramps.
  _legendGradientPaint(svg, cmap) {
    const ns = "http://www.w3.org/2000/svg";
    const id = `xy-legend-grad-${legendGradientSeq++}`;
    const defs = document.createElementNS(ns, "defs");
    const grad = document.createElementNS(ns, "linearGradient");
    grad.setAttribute("id", id);
    const stops = colormapStops(cmap);
    stops.forEach((c, i) => {
      const stop = document.createElementNS(ns, "stop");
      stop.setAttribute("offset", `${(i / Math.max(1, stops.length - 1)) * 100}%`);
      stop.setAttribute("stop-color", `rgb(${c[0]},${c[1]},${c[2]})`);
      grad.appendChild(stop);
    });
    defs.appendChild(grad);
    svg.appendChild(defs);
    return `url(#${id})`;
  }

  // Legend hover emphasis: the hovered row's series keeps full opacity while
  // every other series dims (and, for a categorical row, the trace's other
  // categories dim through a background-blended palette LUT — the point
  // shaders ignore LUT alpha, so the fade is baked into the RGB ramp).
  // Whole density-tier traces dim through _drawDensity's uniform like any
  // other series; a categorical row dims siblings inside an aggregated plane
  // at CELL granularity (_densityRgbaDimmed — §28-recorded approximation).
  _setLegendHover(item, lg, hoveredRow) {
    if (item.off) return; // a hidden series has nothing to emphasize
    this._legendHover = item;
    const keep = new Set(item.traces);
    // Resolved once for the whole pass: every blend below wants the same
    // backdrop, and resolving it per trace would re-walk the ancestor chain
    // (a forced style recalc) and defeat the _lutCache hit.
    const bg = chartBackdrop(this.root, this.theme.bg);
    for (let i = 0; i < (this.gpuTraces || []).length; i++) {
      const g = this.gpuTraces[i];
      g._legendDim = keep.has(i) ? 1 : LEGEND_DIM_OPACITY;
      this._restoreLegendLuts(g);
      const t = g.trace;
      if (item.cat != null && keep.has(i) &&
          t.color && t.color.mode === "categorical") {
        if (g.tier === "density") {
          // The plane cannot dim sibling categories exactly (§28), but its
          // mean-color cells carry the categories' own drawn colors, so the
          // LUT-dim rule applies at CELL granularity: classify each cell by
          // nearest palette color and blend sibling cells toward the
          // background; the hovered category's cells keep their full color.
          // Mixed boundary cells dim by their nearest class — the recorded
          // approximation of the exact per-point dim.
          const d = g.density;
          if (d && d.rgba && d.tex) {
            g._legendHoverPrevTex = d.tex;
            g._legendHoverTex = this._uploadGrid(
              d.grid, d.w, d.h, d.normMax ?? d.max,
              this._densityRgbaDimmed(d.rgba, t.color.palette, item.cat, bg),
              d.filter, this._fillOpacity(t.style),
            );
            d.tex = g._legendHoverTex;
          }
          // The retained sample overlays ARE per-point scatters, so they dim
          // siblings exactly, through the same palette LUT.
          for (const s of this._densityOverlays(g)) {
            this._dimLut(s, t.color.palette, item.cat, bg);
          }
        } else if (g._cpuFunnel) {
          // A funnel carries resolved RGBA rows, not a palette LUT, so the
          // sibling dim recolors the rows themselves with the same blend
          // rule _paletteLutDimmed applies to LUT entries.
          this._dimFunnelPaint(g, item.cat, bg);
        } else {
          this._dimLut(g, t.color.palette, item.cat, bg);
        }
      }
    }
    for (const pair of lg._xyItemRows || []) {
      pair.row.style.opacity = pair.it.off
        ? String(LEGEND_OFF_ROW)
        : pair.row === hoveredRow ? "" : String(LEGEND_DIM_ROW);
    }
    // Color-pass-only change: geometry and view are untouched, so the pick
    // snapshot stays valid (§17).
    this.draw(true);
  }

  _clearLegendHover() {
    if (!this._legendHover) return;
    this._legendHover = null;
    for (const g of this.gpuTraces || []) {
      delete g._legendDim;
      this._restoreLegendLuts(g);
    }
    for (const lg of this._legends || []) {
      for (const pair of lg._xyItemRows || []) this._syncLegendRow(pair.row, pair.it);
    }
    this.draw(true);
  }

  // The per-point scatter entries a density-tier trace keeps alongside its
  // aggregated plane (the retained deterministic sample and, when a reply
  // carried one, the density's own overlay). Deduped: the two are often the
  // same object.
  _densityOverlays(g) {
    return new Set([g.sampleOverlay, g.density && g.density.overlay].filter(Boolean));
  }

  // Swap a scatter-shaped entry's palette LUT for the hover-dimmed variant,
  // stashing the original for _restoreLegendLuts.
  _dimLut(s, palette, keepIdx, bg) {
    if (!s || !s.lut) return;
    s._legendPrevLut = s.lut;
    s.lut = this._paletteLutDimmed(palette, keepIdx, bg);
  }

  // Legend-hover sibling dim for a funnel: the hovered stage keeps its full
  // color, every other stage blends toward the backdrop by the same
  // LEGEND_DIM_OPACITY weight the LUT path uses. Rebuilt from the retained
  // full rows, uploaded through the shared filter-aware path.
  _dimFunnelPaint(g, keepCode, bg) {
    const full = g._funnelRgbaFull;
    const codes = g._funnelCodes;
    if (!full || !codes) return;
    const rows = new Uint8Array(full.length);
    for (let i = 0; i * 4 < full.length; i++) {
      const keep = Math.round(codes[i]) === keepCode;
      const w = keep ? 1 : LEGEND_DIM_OPACITY;
      rows[i * 4] = full[i * 4] * w + bg[0] * 255 * (1 - w);
      rows[i * 4 + 1] = full[i * 4 + 1] * w + bg[1] * 255 * (1 - w);
      rows[i * 4 + 2] = full[i * 4 + 2] * w + bg[2] * 255 * (1 - w);
      rows[i * 4 + 3] = full[i * 4 + 3];
    }
    g._funnelHoverDim = true;
    this._uploadFunnelPaint(g, rows);
  }

  // Undo any hover LUT swap on a trace and its density sample overlays,
  // and put back the plane's original texture if hover dimmed it.
  _restoreLegendLuts(g) {
    for (const s of new Set([g, ...this._densityOverlays(g)])) {
      if (s._legendPrevLut !== undefined) {
        s.lut = s._legendPrevLut;
        delete s._legendPrevLut;
      }
    }
    if (g._legendHoverTex) {
      // A density reply may have replaced g.density mid-hover; only restore
      // onto the object still wearing the hover texture.
      if (g.density && g.density.tex === g._legendHoverTex) {
        g.density.tex = g._legendHoverPrevTex;
      }
      this.gl.deleteTexture(g._legendHoverTex);
      g._legendHoverTex = null;
      g._legendHoverPrevTex = null;
    }
    if (g._funnelHoverDim) {
      delete g._funnelHoverDim;
      this._uploadFunnelPaint(g);
    }
  }

  // Per-cell sibling dim for an aggregated categorical plane: each occupied
  // cell classified by nearest palette color, non-hovered classes blended
  // toward the background exactly like `_paletteLutDimmed` blends LUT
  // entries. Alpha (the physical compositing of the cell's own points, LOD
  // doc §2) is untouched — the dim is a color statement, not a count one.
  _densityRgbaDimmed(rgba, palette, keepIdx, bg = chartBackdrop(this.root, this.theme.bg)) {
    const cls = this._densityCellClasses(rgba, palette);
    const keep = keepIdx % palette.length;
    const w = LEGEND_DIM_OPACITY;
    const out = new Uint8Array(rgba.length);
    for (let i = 0, c = 0; i < rgba.length; i += 4, c++) {
      const a = rgba[i + 3];
      out[i + 3] = a;
      if (!a) continue;
      if (cls[c] === keep) {
        out[i] = rgba[i]; out[i + 1] = rgba[i + 1]; out[i + 2] = rgba[i + 2];
      } else {
        out[i] = (rgba[i] / 255 * w + bg[0] * (1 - w)) * 255;
        out[i + 1] = (rgba[i + 1] / 255 * w + bg[1] * (1 - w)) * 255;
        out[i + 2] = (rgba[i + 2] / 255 * w + bg[2] * (1 - w)) * 255;
      }
    }
    return out;
  }

  // Nearest-palette class per occupied cell of a mean-color plane. Depends
  // only on (rgba, palette) — NOT on which row is hovered — so it is memoized
  // against the plane's own buffer: scanning a legend's rows reclassifies the
  // same grid once instead of once per row. Weak-keyed, so the map dies with
  // the grid it describes (a reply replaces `density.rgba` wholesale).
  _densityCellClasses(rgba, palette) {
    if (!this._dimClassCache) this._dimClassCache = new WeakMap();
    const paletteKey = palette.join(",");
    const memo = this._dimClassCache.get(rgba);
    if (memo && memo.paletteKey === paletteKey) return memo.classes;
    const cols = this._paletteRgb(palette);
    const classes = new Uint8Array(rgba.length / 4);
    for (let i = 0, c = 0; i < rgba.length; i += 4, c++) {
      if (!rgba[i + 3]) continue;
      const r = rgba[i] / 255, gc = rgba[i + 1] / 255, b = rgba[i + 2] / 255;
      let best = 0, bestD = Infinity;
      for (let k = 0; k < cols.length; k++) {
        const dr = r - cols[k][0], dg = gc - cols[k][1], db = b - cols[k][2];
        const dist = dr * dr + dg * dg + db * db;
        if (dist < bestD) { bestD = dist; best = k; }
      }
      classes[c] = best;
    }
    this._dimClassCache.set(rgba, { paletteKey, classes });
    return classes;
  }

  // Toggled-off rows stay visible but read as inactive. Opacity/filter are
  // deliberate renderer-owned interaction state, so they remain inline and
  // outrank ordinary utilities while active; the data attribute lets authors
  // target that boundary explicitly (including with an important utility).
  _syncLegendRow(row, it) {
    const off = !!it.off;
    row.style.opacity = off ? String(LEGEND_OFF_ROW) : "";
    row.style.filter = off ? "grayscale(1)" : "";
    if (off) row.dataset.xyLegendOff = "";
    else delete row.dataset.xyLegendOff;
  }

  // Legend click-to-toggle (interaction spec §10). Whole-trace rows hide
  // locally — buffers and density grids are per-trace, so there is nothing
  // to re-aggregate. Category rows are a §34 filter predicate: direct-tier
  // traces re-filter from the CPU columns already on the client (0 wire
  // bytes, §37 filter-toggle row), density tiers drop their now-stale local
  // aggregates and re-request a kernel re-bin computed under the mask.
  // Either way the kernel records the state so selections stay truthful.
  _legendToggle(it, row) {
    const off = !it.off;
    it.off = off;
    this._clearLegendHover();
    this._syncLegendRow(row, it);
    this._hideTooltip?.();
    if (it.cat != null) {
      const ti = it.traces[0];
      let set = this._legendOffCats.get(ti);
      if (!set) this._legendOffCats.set(ti, (set = new Set()));
      if (off) set.add(it.cat);
      else set.delete(it.cat);
      if (this.comm) {
        this.comm.send({
          type: "legend_toggle", trace: this.spec.traces[ti].id, category: it.cat, hidden: off,
        });
      }
      this._applyCategoryVisibility(ti);
    } else {
      for (const ti of it.traces) {
        if (off) this._legendOffTraces.add(ti);
        else this._legendOffTraces.delete(ti);
        const g = this.gpuTraces && this.gpuTraces[ti];
        if (g) g._legendHidden = off;
        if (this.comm) {
          this.comm.send({ type: "legend_toggle", trace: this.spec.traces[ti].id, hidden: off });
        }
      }
      this._refreshReductionBadges();
    }
    this._pickDirty = true;
    this._updatePickable();
    this._dispatchChartEvent("legendtoggle", {
      name: it.name,
      hidden: off,
      traces: it.traces.map((ti) => this.spec.traces[ti].id),
      ...(it.cat != null ? { category: it.cat } : {}),
    });
    this.draw();
  }

  _applyCategoryVisibility(ti) {
    const g = this.gpuTraces && this.gpuTraces[ti];
    if (!g) return;
    const hidden = this._legendOffCats.get(ti);
    if (g.tier === "density") {
      // Local aggregates were computed unfiltered — stale under the new
      // predicate (§34), and a cached window that still "serves" the view
      // would elide the kernel request that applies the mask. Drop them and
      // re-request. The retained sample overlays are filtered locally so
      // the pre-reply frame (and the kernel-less standalone page) stops
      // drawing the hidden category immediately.
      lodDropPointCache(this, g);
      this._dropDrill(g);
      lodDropDensityCache(this, g);
      // The live home grid survives the cache drop (it is what draws until
      // the reply) but must not elide the request — it was binned under the
      // previous mask (§34).
      g._filterDirty = true;
      for (const s of this._densityOverlays(g)) this._filterScatterRows(s, hidden);
      this._scheduleViewRequest(this.view, { delay: 0 });
    } else if (g._cpuFunnel) {
      this._filterFunnelStages(g, hidden);
    } else {
      this._filterScatterRows(g, hidden);
    }
  }

  // Hiding a funnel stage removes that segment and nothing else: the stage
  // axis keeps its label and the surviving stages keep their own geometry and
  // conversion arithmetic, because a funnel's stage values are the data, not
  // a running total to be recomputed. Small-N, so the six instance columns and
  // the paint rows are simply rebuilt from the retained CPU views rather than
  // read back off the GPU the way the scatter filter must.
  _filterFunnelStages(g, hidden) {
    const f = g._cpuFunnel;
    if (!f) return;
    const codes = g._funnelCodes;
    const visible = [];
    for (let i = 0; i < f.n; i++) {
      const code = codes ? Math.round(codes[i]) : i;
      if (!hidden || !hidden.has(code)) visible.push(i);
    }
    // `_visMap` translates drawn instance → shipped stage row, so hover,
    // tooltips and events keep naming the right stage while filtered.
    g._visMap = visible.length === f.n ? null : Int32Array.from(visible);
    g.n = visible.length;
    for (const [name, slot] of Object.entries(FUNNEL_SLOTS)) {
      const source = f[name];
      const values = g._visMap
        ? Float32Array.from(visible, (i) => source[i])
        : source;
      this._deleteBuffers(g, [slot + "Buf"]);
      g[slot + "Buf"] = this._upload(values);
    }
    this._uploadFunnelPaint(g);
  }

  // Filter a scatter-shaped gpu entry's vertex buffers down to the rows whose
  // categorical code is not hidden; an empty/absent set restores the full
  // buffers. Gathers from the CPU views retained at build; per-point
  // style/stroke buffers have no retained CPU copy, so they are read back
  // once (WebGL2 getBufferSubData) and cached for later re-toggles.
  // `_visMap` translates drawn vertex → shipped row (picks/readouts);
  // `_visInv` maps shipped selection indices onto the filtered buffers.
  _filterScatterRows(g, hidden) {
    const gl = this.gl;
    const codes = g._cpu && g._cpu.color;
    if (!gl || !codes || g.colorMode !== 2) return;
    if (g._fullN === undefined) g._fullN = g.n;
    const full = g._fullN;
    const readback = (buf, Type, comps) => {
      const out = new Type(full * comps);
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.getBufferSubData(gl.ARRAY_BUFFER, 0, out);
      return out;
    };
    if (g.styleBuf && !g._cpuStyle) g._cpuStyle = readback(g.styleBuf, Float32Array, 4);
    if (g.strokeBuf && !g._cpuStroke) g._cpuStroke = readback(g.strokeBuf, Uint8Array, 4);
    let vis = null;
    if (hidden && hidden.size) {
      const idx = new Uint32Array(full);
      let m = 0;
      for (let i = 0; i < full; i++) if (!hidden.has(codes[i])) idx[m++] = i;
      vis = idx.subarray(0, m);
    }
    const gather = (src, comps) => {
      if (!vis) return src.length === full * comps ? src : src.subarray(0, full * comps);
      const out = new (src.constructor)(vis.length * comps);
      for (let j = 0; j < vis.length; j++) {
        const r = vis[j];
        for (let c = 0; c < comps; c++) out[j * comps + c] = src[r * comps + c];
      }
      return out;
    };
    const reupload = (buf, data) => {
      if (!buf || !data) return;
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    };
    reupload(g.xBuf, gather(g._cpu.x, 1));
    reupload(g.yBuf, gather(g._cpu.y, 1));
    reupload(g.cBuf, gather(codes, 1));
    if (g.sBuf && g._cpu.size) reupload(g.sBuf, gather(g._cpu.size, 1));
    if (g.styleBuf && g._cpuStyle) reupload(g.styleBuf, gather(g._cpuStyle, 4));
    if (g.strokeBuf && g._cpuStroke) reupload(g.strokeBuf, gather(g._cpuStroke, 4));
    g.n = vis ? vis.length : full;
    if (vis) {
      g._visMap = vis;
      const inv = new Int32Array(full).fill(-1);
      for (let j = 0; j < vis.length; j++) inv[vis[j]] = j;
      g._visInv = inv;
    } else {
      delete g._visMap;
      delete g._visInv;
    }
    // A per-vertex selection mask built for the other vertex count would
    // highlight arbitrary points; the kernel's canonical Selection (already
    // hidden-aware) re-syncs the visual on the next brush.
    g.selActive = false;
    this._pickDirty = true;
  }

  // Rebuilds (context restore, streaming append) recreate gpuTraces from the
  // spec, dropping transient per-trace state; toggle state lives on the view
  // and is re-applied here after every rebuild.
  _reapplyLegendVisibility() {
    if (!this._legendOffTraces && !this._legendOffCats) return;
    for (let i = 0; i < (this.gpuTraces || []).length; i++) {
      const g = this.gpuTraces[i];
      if (this._legendOffTraces && this._legendOffTraces.has(i)) g._legendHidden = true;
      const cats = this._legendOffCats && this._legendOffCats.get(i);
      if (!cats || !cats.size) continue;
      if (g.tier === "density") {
        // The rebuilt grid comes from the spec — unfiltered — so the next
        // view request must re-bin under the mask, not stand on it.
        g._filterDirty = true;
        if (g.sampleOverlay) this._filterScatterRows(g.sampleOverlay, cats);
      } else if (g._cpuFunnel) {
        // _filterScatterRows is gated on CPU color codes a funnel does not
        // have — routing a rebuilt funnel there silently un-hid its stages.
        this._filterFunnelStages(g, cats);
      } else {
        this._filterScatterRows(g, cats);
      }
    }
  }

  _positionLegend(lg, loc, anchor = null) {
    if (!lg) return;
    // Responsive anchors flow through private custom properties consumed by a
    // zero-specificity rule. Author classes or component styles can still set
    // real left/right/top/bottom/transform declarations and win normally.
    //
    // Cartesian legends place inside the plot rect; a polar chart hands over a
    // gutter beside the disc instead (`_recutPolarPlot`), because a disc fills
    // its rect and an inside box lands on the marks. An authored `anchor` is
    // still resolved against the PLOT — it is a plot-relative coordinate — and
    // reserves no gutter, so the two cannot disagree.
    const plot = anchor ? this.plot : (this._legendRect || this.plot);
    const rightInset = this.size.w - (plot.x + plot.w);
    const h = loc.includes("left") ? "left" : loc.includes("right") ? "right" : "center";
    const locTokens = loc.split(/[\s_-]+/);
    const v = loc.includes("upper") || locTokens.includes("top")
      ? "upper"
      : loc.includes("lower") || locTokens.includes("bottom")
        ? "lower"
        : "center";
    let left = h === "left" ? this.plot.x + 6 : h === "center" ? this.plot.x + this.plot.w / 2 : null;
    let right = h === "right" ? rightInset + 6 : null;
    let top = v === "upper" ? this.plot.y + 6 : v === "center" ? this.plot.y + this.plot.h / 2 : null;
    let bottom = v === "lower" ? this.size.h - (this.plot.y + this.plot.h) + 6 : null;
    if (Array.isArray(anchor) && (anchor.length === 2 || anchor.length === 4)) {
      const hx = h === "left" ? 0 : h === "right" ? 1 : 0.5;
      const vy = v === "lower" ? 0 : v === "upper" ? 1 : 0.5;
      const aw = anchor.length === 4 ? Number(anchor[2]) : 0;
      const ah = anchor.length === 4 ? Number(anchor[3]) : 0;
      const borderPad = Math.max(0, Number(lg.dataset.xyLegendBorderPad) || 0);
      left = this.plot.x + (Number(anchor[0]) + hx * aw) * this.plot.w +
        (hx === 0 ? borderPad : hx === 1 ? -borderPad : 0);
      top = this.plot.y + (1 - Number(anchor[1]) - vy * ah) * this.plot.h +
        (vy === 1 ? borderPad : vy === 0 ? -borderPad : 0);
      right = null;
      bottom = null;
    }
    lg.style.setProperty("--xy-legend-left", left == null ? "auto" : left + "px");
    lg.style.setProperty("--xy-legend-right", right == null ? "auto" : right + "px");
    lg.style.setProperty("--xy-legend-top", top == null ? "auto" : top + "px");
    lg.style.setProperty("--xy-legend-bottom", bottom == null ? "auto" : bottom + "px");
    const tx = h === "center" ? "-50%" : h === "right" && anchor ? "-100%" : "0";
    const ty = v === "center" ? "-50%" : v === "lower" && anchor ? "-100%" : "0";
    lg.style.setProperty("--xy-legend-transform", `translate(${tx},${ty})`);
  }

  _buildColorbar(root) {
    const cb = this.spec.colorbar;
    if (!cb) return;
    const box = document.createElement("div");
    const horizontal = cb.orientation === "horizontal";
    const axesPlacement = cb.placement === "axes";
    box.style.cssText = "position:absolute;pointer-events:none;z-index:4;";
    this._applySlot(box, "colorbar");

    const bar = document.createElement("div");
    const levels = Math.max(0, Number(cb.levels) || 0);
    const lineOnly = Boolean(cb.line_only);
    let gradient;
    if (lineOnly) {
      gradient = "linear-gradient(white,white)";
    } else if (levels > 0) {
      const lut = buildLutData(cb.colormap || "viridis");
      const exactColors = Array.isArray(cb.band_colors) && cb.band_colors.length === levels
        ? cb.band_colors
        : null;
      const boundaries = Array.isArray(cb.boundaries)
        ? cb.boundaries.map(Number)
        : [];
      const proportional =
        cb.spacing === "proportional" &&
        boundaries.length === levels + 1 &&
        boundaries.every(Number.isFinite) &&
        boundaries.every((value, index) => index === 0 || value > boundaries[index - 1]);
      const fractions = proportional
        ? boundaries.map(
          (value) =>
            (value - boundaries[0]) /
            (boundaries[boundaries.length - 1] - boundaries[0]),
        )
        : Array.from({ length: levels + 1 }, (_, index) => index / levels);
      const bands = [];
      for (let index = 0; index < levels; index++) {
        const sample = Math.min(255, Math.round(255 * (index + 0.5) / levels));
        const row = exactColors && exactColors[index];
        const color = row
          ? `rgb(${Number(row[0])},${Number(row[1])},${Number(row[2])})`
          : `rgb(${lut[sample * 4]},${lut[sample * 4 + 1]},${lut[sample * 4 + 2]})`;
        bands.push(`${color} ${100 * fractions[index]}% ${100 * fractions[index + 1]}%`);
      }
      gradient = `linear-gradient(to ${horizontal ? "right" : "top"},${bands.join(",")})`;
    } else {
      const stops = colormapStops(cb.colormap || "viridis");
      gradient = `linear-gradient(to ${horizontal ? "right" : "top"},${stops.map((c) =>
        `rgb(${c[0]},${c[1]},${c[2]})`).join(",")})`;
    }
    const barThickness = axesPlacement
      ? (horizontal ? this.plot.h : this.plot.w)
      : COLORBAR_THICKNESS;
    bar.style.cssText = horizontal
      ? `position:absolute;inset:0 0 auto 0;height:${barThickness}px;`
      : `position:absolute;inset:0 auto 0 0;width:${barThickness}px;`;
    bar.style.setProperty("--xy-colorbar-gradient", gradient);
    if (lineOnly) {
      bar.dataset.xyColorbarLineOnly = "true";
    }
    this._applySlot(bar, "colorbar_bar");
    box.appendChild(bar);
    if (lineOnly && ["min", "max", "both"].includes(String(cb.extend))) {
      const extension = (side) => {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        const polygon = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        const atMinimum = side === "min";
        svg.dataset.xyColorbarExtend = side;
        svg.setAttribute("width", String(horizontal ? 9 : barThickness));
        svg.setAttribute("height", String(horizontal ? barThickness : 9));
        svg.style.cssText = horizontal
          ? `position:absolute;top:0;${atMinimum ? "right:100%" : "left:100%"};overflow:visible;`
          : `position:absolute;left:0;${atMinimum ? "top:100%" : "bottom:100%"};overflow:visible;`;
        polygon.setAttribute("points", horizontal
          ? (atMinimum
            ? `9,0 9,${barThickness} 0,${barThickness / 2}`
            : `0,0 0,${barThickness} 9,${barThickness / 2}`)
          : (atMinimum
            ? `0,0 ${barThickness},0 ${barThickness / 2},9`
            : `0,9 ${barThickness},9 ${barThickness / 2},0`));
        polygon.setAttribute("fill", "white");
        polygon.setAttribute("stroke", "currentColor");
        this._applySlot(polygon, "colorbar_extension");
        svg.appendChild(polygon);
        bar.appendChild(svg);
      };
      if (cb.extend === "min" || cb.extend === "both") extension("min");
      if (cb.extend === "max" || cb.extend === "both") extension("max");
    }

    const domain = cb.domain || [0, 1];
    const lo = Number(domain[0]), hi = Number(domain[1]);
    const span = hi - lo || 1;
    const logScale = cb.scale === "log";
    const colorbarFraction = (value) => logScale
      ? (hi === lo ? 0 : Math.log(value / lo) / Math.log(hi / lo))
      : (value - lo) / span;
    for (const line of Array.isArray(cb.lines) ? cb.lines : []) {
      const value = Number(line && line.value);
      if (!Number.isFinite(value) || value < Math.min(lo, hi) || value > Math.max(lo, hi)) continue;
      const fraction = colorbarFraction(value);
      const marker = document.createElement("i");
      marker.dataset.xyColorbarLine = "true";
      const color = safeCssPaint(this.root, line.color || "currentColor");
      const width = Math.max(0.5, Number(line.width) || 1);
      const lineStyle = line.dash === "dashed" ? "dashed" : "solid";
      marker.dataset.xyColorbarOrientation = horizontal ? "horizontal" : "vertical";
      marker.style.cssText = horizontal
        ? `position:absolute;left:${100 * fraction}%;inset-block:0;`
        : `position:absolute;top:${100 * (1 - fraction)}%;inset-inline:0;`;
      marker.style.setProperty("--xy-colorbar-line-width", `${width}px`);
      marker.style.setProperty("--xy-colorbar-line-style", lineStyle);
      marker.style.setProperty("--xy-colorbar-line-color", color);
      this._applySlot(marker, "colorbar_line");
      bar.appendChild(marker);
    }
    const shrink = Math.max(0.01, Math.min(1, Number(cb.shrink) || 1));
    const barLength = (horizontal ? this.plot.w : this.plot.h) * shrink;
    const tickTarget = Math.max(2, Math.min(8, Math.floor(Math.max(0, barLength) / 48) + 1));
    const tickResult = logScale ? logTicks(lo, hi, tickTarget) : linearTicks(lo, hi, tickTarget);
    const hasExplicitTicks = Array.isArray(cb.ticks);
    const tickValues = hasExplicitTicks
      ? cb.ticks
      : (logScale ? (tickResult as any).labels : tickResult.ticks);
    const tickStep = tickResult.step;
    const fractionFor = (value) => logScale
      ? (hi === lo ? 0 : Math.log(value / lo) / Math.log(hi / lo))
      : (value - lo) / span;
    for (let tickIndex = 0; tickIndex < tickValues.length; tickIndex++) {
      const raw = tickValues[tickIndex];
      const value = Number(raw);
      if (!Number.isFinite(value) || value < Math.min(lo, hi) || value > Math.max(lo, hi)) continue;
      // `any` because the node carries the stashed beside-the-bar cssText below
      // (same reason as the legend box's `lg`).
      const tick: any = document.createElement("span");
      tick.textContent =
        hasExplicitTicks &&
          Array.isArray(cb.tick_labels) &&
          cb.tick_labels.length === tickValues.length
          ? String(cb.tick_labels[tickIndex])
          : hasExplicitTicks
            ? fmtGeneral(value)
            : logScale
              ? fmtLog(value)
              : fmtLinear(value, tickStep);
      const fraction = fractionFor(value);
      // The compact vertical form keeps only the two extreme ticks (see
      // `_positionColorbar`), so record each tick's position on the node and let
      // positioning decide — the tick VALUES are generated here, and which of
      // them survive is a responsive decision that changes with the container.
      tick.dataset.xyColorbarFraction = String(fraction);
      tick.style.cssText = horizontal
        ? `position:absolute;left:${100 * fraction}%;top:${barThickness + 2}px;transform:translateX(-50%);white-space:nowrap;`
        : `position:absolute;left:${barThickness + 5}px;top:${100 * (1 - fraction)}%;transform:translateY(-50%);white-space:nowrap;`;
      // The compact form restacks the two endpoints above/below the gradient, so
      // keep the beside-the-bar placement to restore when the container widens.
      tick._xyBesideCss = tick.style.cssText;
      this._applySlot(tick, "colorbar_tick");
      box.appendChild(tick);
    }
    if (cb.minor_ticks) {
      const orderedTicks = [...tickValues]
        .map(Number)
        .filter(Number.isFinite)
        .sort((a, b) => a - b);
      for (let index = 0; index + 1 < orderedTicks.length; index++) {
        const left = orderedTicks[index], right = orderedTicks[index + 1];
        for (let step = 1; step < 5; step++) {
          const value = logScale
            ? Math.pow(10, Math.log10(left) + (Math.log10(right) - Math.log10(left)) * step / 5)
            : left + (right - left) * step / 5;
          const fraction = fractionFor(value);
          const tick = document.createElement("i");
          tick.dataset.xyColorbarMinor = "true";
          tick.dataset.xyColorbarOrientation = horizontal ? "horizontal" : "vertical";
          tick.style.cssText = horizontal
            ? `position:absolute;left:${100 * fraction}%;top:${barThickness}px;`
            : `position:absolute;left:${barThickness}px;top:${100 * (1 - fraction)}%;`;
          this._applySlot(tick, "colorbar_minor_tick");
          box.appendChild(tick);
        }
      }
    }
    if (cb.label) {
      const label = document.createElement("span");
      label.textContent = String(cb.label);
      label.style.cssText = horizontal
        ? `position:absolute;left:50%;top:${barThickness + 18}px;transform:translateX(-50%);white-space:nowrap;`
        : `position:absolute;left:${barThickness + 40}px;top:50%;writing-mode:vertical-rl;transform:translateY(-50%) rotate(180deg);white-space:nowrap;`;
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
    const cb = this.spec.colorbar || {};
    const horizontal = this._colorbarHorizontal;
    const axesPlacement = cb.placement === "axes";
    const compactVertical = !horizontal && this._compactVerticalColorbar;
    const gap = axesPlacement
      ? 0
      : (cb.pad == null
        ? (compactVertical ? COMPACT_COLORBAR_GAP : COLORBAR_GAP)
        : Number(cb.pad) * (horizontal ? this.plot.h : this.plot.w));
    const shrink = Math.max(0.01, Math.min(1, Number(cb.shrink) || 1));
    const anchor = Array.isArray(cb.anchor) ? cb.anchor : [0.5, 0.5];
    const barWidth = this.plot.w * shrink;
    const barHeight = this.plot.h * shrink;
    this._colorbar.style.left = (horizontal
      ? axesPlacement
        ? this.plot.x
        : this.plot.x + (this.plot.w - barWidth) * Number(anchor[0] ?? 0.5)
      : axesPlacement
        ? this.plot.x
        : this.plot.x + this.plot.w + this._rightAxisRoom + gap) + "px";
    this._colorbar.style.top = (horizontal
      ? axesPlacement
        ? this.plot.y
        : this.plot.y + this.plot.h + gap
      : this.plot.y + (this.plot.h - barHeight) * (1 - Number(anchor[1] ?? 0.5))) + "px";
    this._colorbar.style.width = (horizontal
      ? axesPlacement ? this.plot.w : barWidth
      : axesPlacement ? this.plot.w + 44 : compactVertical ? COLORBAR_THICKNESS : 66) + "px";
    this._colorbar.style.height = (horizontal
      ? axesPlacement ? this.plot.h + 24 : 50
      : Math.max(24, barHeight)) + "px";
    this._colorbar.dataset.xyCompact = compactVertical ? "true" : "false";
    // Compact keeps the two EXTREME tick labels — hiding all of them left a bare
    // gradient with no numbers on it — and restacks them above and below the
    // gradient. Beside the bar they would need a gutter wide enough for `0.25`,
    // which costs 36 px of the plot width the compact collapse exists to protect;
    // centred on an 18 px bar they overflow ~4 px a side into the gap already
    // reserved. The interior ladder still drops, and so does the rotated title:
    // at phone width it has nowhere to go, and the box's own `title`/ARIA text
    // already names the scale and its range.
    const ticks = [...this._colorbar.querySelectorAll('[data-xy-slot="colorbar_tick"]')];
    const fractions = ticks.map((node) => Number(node.dataset.xyColorbarFraction));
    const lowest = Math.min(...fractions);
    const highest = Math.max(...fractions);
    for (const [index, node] of ticks.entries()) {
      const fraction = fractions[index];
      const endpoint = !Number.isFinite(fraction) || fraction === lowest || fraction === highest;
      node.hidden = compactVertical && !endpoint;
      if (horizontal || !node._xyBesideCss) continue;
      if (!compactVertical || !endpoint) {
        node.style.cssText = node._xyBesideCss;
        continue;
      }
      // Above the top of the gradient for the maximum, below the bottom for the
      // minimum, both centred on the bar.
      const above = fraction === highest;
      const offset = COMPACT_COLORBAR_LABEL_GAP;
      node.style.cssText =
        "position:absolute;left:50%;white-space:nowrap;" +
        (above
          ? `top:-${offset}px;transform:translate(-50%,-100%);`
          : `top:calc(100% + ${offset}px);transform:translateX(-50%);`);
    }
    // The rotated title and the text-free minor ticks are ink a phone-width chart
    // cannot spend; `box.title` keeps the scale name reachable.
    for (const node of this._colorbar.querySelectorAll(
      '[data-xy-slot="colorbar_title"], [data-xy-colorbar-minor]'
    )) {
      node.hidden = compactVertical;
    }
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

    // A visible chart canvas is a normal 2D DOM surface; a detached GLHost
    // owns the one WebGL2 context for every ChartView in this document. Keep a
    // guarded native path for child frames, explicit rollback, and host
    // allocation failure — that path retains the proven context governor.
    if (!this._sharedGlAttempted) {
      this._sharedGlAttempted = true;
      const host = acquireGLHost(document, this);
      if (host) {
        const present = this.canvas.getContext("2d", { alpha: true });
        if (present) {
          this._glHost = host;
          this._present2d = present;
          this.canvas.dataset.xyGlHost = "shared";
        } else {
          host.release(this);
        }
      }
    }

    let gl;
    if (this._glHost) {
      gl = this._glHost.gl;
      if (!gl || gl.isContextLost()) throw new Error("webgl2 unavailable");
    } else {
      if (!this._governorRegistered) {
        XY_CONTEXT_GOVERNOR.register(this);
        this._governorRegistered = true;
      }
      // Stay inside the page's context budget before acquiring (governor
      // fallback): at budget, the least-recently-visible view releases first.
      XY_CONTEXT_GOVERNOR.reserve(this);
      gl = this.canvas.getContext("webgl2", {
        antialias: false, premultipliedAlpha: true, alpha: true,
      });
      if (!gl) {
        XY_CONTEXT_GOVERNOR.cancel(this);
        throw new Error("webgl2 unavailable");
      }
      XY_CONTEXT_GOVERNOR.acquired(this);
    }
    this.gl = gl;
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    // Shader programs compile lazily on first use (small-data audit #2): a
    // simple line chart links one program instead of paying seven unused
    // synchronous compile+links before its first paint.
    this._progCache = new Map();
    this._glPrograms = this._progCache; // deletion iterates the cache values

    // Density/heatmap use one immutable fullscreen quad. It is safe to pool at
    // host scope because fixed attribute slots make its VAO program-agnostic.
    if (this._glHost) {
      this.quad = this._glHost.sharedQuad;
      this.quadVao = this._glHost.sharedQuadVao;
    } else {
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
    }

    // Build transactionally. A lost context or allocation failure midway
    // through a trace list must not strand the buffers/programs already made
    // for its prefix — shared-host recovery may retry this client in place.
    this.gpuTraces = [];
    try {
      for (const trace of this.spec.traces) {
        this.gpuTraces.push(this._buildTrace(buffer, trace));
      }
    } catch (error) {
      try { this._destroyGlResources(); } catch (_cleanupError) {}
      throw error;
    }
    this._reapplyLegendVisibility();
    this._updatePickable();
  }

  // Recompute point-pickability from the current GPU traces and reflect it in
  // the modebar. Density traces count only while drilled to exact points
  // (§5/§34), so this must re-run on every drill state change — the Select
  // trigger tracks the capability instead of freezing at construction time.
  _updatePickable() {
    this._pickable = this.gpuTraces.some(
      (t) => markOf(t.trace.kind).pointPick && (t.tier !== "density" || t.drill));
    if (this._pickable && !this.pickFbo) this._initPickTarget();
    this._syncModebarSelect?.();
  }

  _prog(key, vs, fs) {
    let p = this._progCache.get(key);
    if (!p) {
      // Uniforms are mutable program state. Keep programs client-owned until
      // every mark pass is independently state-complete; sharing them would
      // let one chart's transition/style uniforms leak into another chart.
      const host = this._glHost;
      // The resolver is an additive host capability. A singleton installed by
      // an older duplicate bundle does not expose it, so mixed-version pages
      // safely retain the native per-program shader lifecycle.
      const resolveShader = host && typeof host.getOrCreateShader === "function"
        ? host.getOrCreateShader.bind(host)
        : undefined;
      p = makeProgram(this.gl, vs, fs, resolveShader);
      this._progCache.set(key, p);
    }
    return p;
  }

  get pointProg() { return this._prog("point", POINT_VS, POINT_FS); }
  get pointSimpleProg() { return this._prog("point-simple", POINT_SIMPLE_VS, POINT_SIMPLE_FS); }
  get lineProg() { return this._prog("line", LINE_VS, LINE_FS); }
  get segmentProg() { return this._prog("segment", SEGMENT_VS, SEGMENT_FS); }
  get meshProg() { return this._prog("mesh", MESH_VS, MESH_FS); }
  get ribbonProg() { return this._prog("ribbon", RIBBON_VS, RIBBON_FS); }
  // The funnel program shares the ribbon fragment stage: same edge
  // coverage, stroke inset, and match-fill outline contract.
  get funnelProg() { return this._prog("funnel", FUNNEL_VS, RIBBON_FS); }
  get areaProg() { return this._prog("area", AREA_VS, AREA_FS); }
  get rectProg() { return this._prog("rect", RECT_VS, RECT_FS); }
  get barProg() { return this._prog("bar", BAR_VS, RECT_FS); }
  get pickProg() { return this._prog("pick", PICK_VS, PICK_FS); }
  get densityProg() { return this._prog("density", GRID_VS, DENSITY_FS); }
  get heatmapProg() { return this._prog("heatmap", GRID_VS, HEATMAP_FS); }

  _lut(name) {
    // Keyed by value, not identity: a custom colormap arrives as a fresh
    // stops array on every spec, so caching on the array itself would leak a
    // GL texture per frame.
    const key = colormapKey(name);
    if (this._lutCache.has(key)) return this._lutCache.get(key);
    const gl = this.gl;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, buildLutData(name));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this._lutCache.set(key, tex);
    return tex;
  }

  // One resolved [r,g,b,a] per palette entry. Every palette Python ships is
  // already hex (components._palette_list normalizes it), so this decodes
  // without touching the DOM — which matters: `resolveCssColor`'s probe
  // returns "" while the root is still detached (notebook webviews attach
  // asynchronously), and a palette LUT cached from that state is never
  // rebuilt. The DOM fallback stays for hand-authored specs only.
  _paletteRgb(palette) {
    return palette.map((c) => hexColor(c) || parseColor(this.root, c, [0, 0, 0, 1]));
  }

  _paletteLut(palette) {
    // Cached by palette identity: categorical drill updates request this per
    // zoom step, and an uncached texture per call is a steady GL leak.
    const key = "pal:" + palette.join(",");
    if (this._lutCache.has(key)) return this._lutCache.get(key);
    const gl = this.gl;
    const data = new Uint8Array(256 * 4);
    // Resolve once per palette entry, not once per texel: a chart palette
    // (xy.theme(palette=...)) may hold any CSS color, and parseColor's probe
    // is a forced style recalc. Cache-miss only, so the cost is bounded.
    const rgb = this._paletteRgb(palette);
    for (let i = 0; i < 256; i++) {
      const c = rgb[i % rgb.length];
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

  // Palette LUT with every category except `keepIdx` blended toward the plot
  // background — the legend-hover dim for categorical traces. RGB-only on
  // purpose: the point/line shaders read `texture(u_lut, ...).rgb` and force
  // alpha to 1, so an alpha-based fade would be a silent no-op.
  // `bg` is the resolved backdrop (see chartBackdrop); callers that dim
  // several entries in one pass resolve it once and pass it in. theme.bg is
  // a resolved [r,g,b,a] (or null for a transparent chart, in which case the
  // page paints the backdrop) — never a CSS string, so it must not go
  // through parseColor, which would silently fall back to white and BRIGHTEN
  // dimmed entries on dark pages.
  _paletteLutDimmed(palette, keepIdx, bg = chartBackdrop(this.root, this.theme.bg)) {
    const key = "pal:" + palette.join(",") + ":dim" + keepIdx + ":" + bg.join(",");
    if (this._lutCache.has(key)) return this._lutCache.get(key);
    const gl = this.gl;
    const data = new Uint8Array(256 * 4);
    const rgb = this._paletteRgb(palette);
    for (let i = 0; i < 256; i++) {
      const c = rgb[i % palette.length];
      const keep = i % palette.length === keepIdx % palette.length;
      const w = keep ? 1 : LEGEND_DIM_OPACITY;
      data[i * 4] = (c[0] * w + bg[0] * (1 - w)) * 255;
      data[i * 4 + 1] = (c[1] * w + bg[1] * (1 - w)) * 255;
      data[i * 4 + 2] = (c[2] * w + bg[2] * (1 - w)) * 255;
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
    const g: any = {
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
      // Mean point color plane (LOD doc §2), copied because exposure
      // re-encodes outlive the payload buffer; absent for constant-color
      // traces, which tint the count texture instead.
      const rgba = d.rgba !== undefined
        ? new Uint8Array(this._columnView(buffer, this.spec.columns[d.rgba]))
        : null;
      g.densityNormMax = d.max;
      const filter = d.filter || "linear";
      g.density = {
        w: d.w, h: d.h, max: d.max, normMax: d.max, colormap: d.colormap,
        color: d.color ? parseColor(this.root, d.color, [0.3, 0.47, 0.66, 1]) : null,
        xRange: d.x_range, yRange: d.y_range,
        // The home window's count seeds lodAggregateStands (T13): every
        // zoom's points-band estimate starts from this until a closer
        // window's reply recalibrates it.
        visible: t.visible,
        grid: lodCopyGrid(grid),
        rgba,
        filter,
        tex: this._uploadGrid(grid, d.w, d.h, d.max, rgba, filter, this._fillOpacity(t.style)),
        lut: this._lut(d.colormap),
      };
      g.sampleOverlay = this._buildDensitySample(t, d.sample, buffer);
      // The overlay rides its density window (T9 pairing): the home sample
      // belongs to the home grid, so a deep zoom-out that falls back to the
      // home texture brings the full-extent point sample back with it.
      g.density.overlay = g.sampleOverlay;
      g._shownSampleOverlay = g.sampleOverlay;
      g._shownDensity = g.density;
      lodRememberDensity(this, g, g.density);
      return g;
    }

    // Per-mark GPU setup is dispatched through MARK_KINDS (55_marks.js) so a
    // new chart kind is an entry in that registry, not another branch here.
    markOf(t.kind).build(this, g, t, buffer);
    if (t.tier === "decimated") {
      // T1 covering representation for M4 traces.  Density has its texture
      // cache; decimated line/area traces need the same guarantee while a
      // window-specific re-decimation is in flight.  Keep the initial (home)
      // buffers in a separate drawable so refined replies never overwrite
      // the only geometry that covers the full initial domain.
      g._homeDecimated = {
        ...g, _vaos: null, _homeDecimated: null, _decimatedWindow: null,
      };
      g._decimatedWindow = [...this._axisRange(g.xAxis)];
      g._decimatedRefined = false;
    }
    if (t.keys && Number.isInteger(t.keys.lo) && Number.isInteger(t.keys.hi)) {
      const lo = this._columnView(buffer, this.spec.columns[t.keys.lo]);
      const hi = this._columnView(buffer, this.spec.columns[t.keys.hi]);
      const count = Math.min(g.n || 0, lo.length, hi.length);
      g._transitionKeys = new Array(count);
      g._transitionKeyIndex = new Map();
      for (let i = 0; i < count; i++) {
        const key = `${hi[i]}:${lo[i]}`;
        if (g._transitionKeyIndex.has(key)) throw new Error("xy: duplicate binary animation key");
        g._transitionKeys[i] = key;
        g._transitionKeyIndex.set(key, i);
      }
    }
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

  _buildInstanceStyleChannels(g, t, buffer, widthName) {
    const channel = (name) => t.channels && t.channels[name];
    const artistScalar = Number(t.style && t.style.artist_alpha);
    const hasStyle = channel("opacity") || channel("artist_alpha") ||
      channel(widthName) || channel("symbol") || Number.isFinite(artistScalar);
    if (hasStyle) {
      const values = new Float32Array(g.n * 4);
      for (let i = 0; i < g.n; i++) {
        values[i * 4] = 1;
        values[i * 4 + 1] = Number.isFinite(artistScalar) ? artistScalar : -1;
        values[i * 4 + 2] = -1;
        values[i * 4 + 3] = -1;
      }
      const copy = (name, component, scale = 1) => {
        const spec = channel(name);
        if (!spec) return;
        const source = this._columnView(buffer, this.spec.columns[spec.buf]);
        for (let i = 0; i < g.n; i++) values[i * 4 + component] = source[i * (spec.components || 1)] * scale;
      };
      copy("opacity", 0);
      copy("artist_alpha", 1);
      copy(widthName, 2, this.dpr);
      copy("symbol", 3);
      // Canvas-authored markers consume the same canonical style rows as the
      // point shader.  Keep them CPU-readable instead of treating styleBuf as
      // the only copy; filtering may still gather/reupload from this array.
      g._cpuStyle = values;
      g.styleBuf = this._upload(values);
      // Width rows are baked at the dpr in force right now. Record it so the
      // streaming-append fast path can tell whether a later tail upload would
      // write rows at a different scale than the prefix already holds (§4).
      g._styleDpr = this.dpr;
    }
    const radius = channel("corner_radius");
    if (radius) {
      const source = this._columnView(buffer, this.spec.columns[radius.buf]);
      const components = radius.components || 1;
      const values = new Float32Array(g.n * 2);
      for (let i = 0; i < g.n; i++) {
        values[i * 2] = source[i * components] * this.dpr;
        values[i * 2 + 1] = (components > 1 ? source[i * components + 1] : source[i * components]) * this.dpr;
      }
      // Kept CPU-readable for the same reason as `_cpuStyle`: these rows are
      // baked at the dpr in force right now, and a later dpr change rescales
      // them in place (`_rescaleDprBakedBuffers`) instead of leaving 1x radii
      // on a 2x canvas.
      g._cpuRadius = values;
      g.radiusBuf = this._upload(values);
      // Also stamped here: a trace can carry corner radii without any style
      // channels, and an unstamped record is one the rescale pass skips.
      g._styleDpr = this.dpr;
    }
    if (t.stroke && t.stroke.mode === "direct_rgba") {
      g._cpuStroke = this._columnView(buffer, this.spec.columns[t.stroke.buf]);
      g.strokeBuf = this._upload(g._cpuStroke);
    }
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
    } else if (t.color && t.color.mode === "direct_rgba") {
      g.colorMode = 3;
      g._cpu.rgba = this._columnView(buffer, this.spec.columns[t.color.buf]);
      g.rgbaBuf = this._upload(g._cpu.rgba);
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
    this._buildInstanceStyleChannels(g, t, buffer, "stroke_width");
    this._pointMarkStyle(g, t);
  }

  // Point symbol + stroke (scatter). An omitted stroke color means "face":
  // use each point's resolved LUT/palette color, never a generic trace color.
  _pointMarkStyle(g, t) {
    const s = t.style || {};
    g.authoredMarker = s.marker_path || s.marker_glyph || null;
    g.symbol = { circle: 0, square: 1, diamond: 2, triangle: 3, cross: 4, hexagon: 5, pentagon: 6, star: 7, triangle_down: 8, triangle_left: 9, triangle_right: 10, x: 11, point: 12, pixel: 13, thin_diamond: 14, plus_line: 15, x_line: 16, horizontal_line: 17, vertical_line: 18 }[s.symbol] || 0;
    g.pointStrokeWidth = Number(s.stroke_width) || 0;
    g.pointStrokeFace = !s.stroke && (!t.stroke || t.stroke.mode === "match_fill");
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
      stroke: sample.stroke,
      channels: sample.channels,
    };
  }

  _buildDensitySample(parentTrace, sample, buffer) {
    if (!sample || !sample.x || !sample.y || sample.x.col === undefined || sample.y.col === undefined) {
      return null;
    }
    const trace = this._sampleTraceSpec(parentTrace, sample);
    const g: any = {
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

  _destroySampleOverlay(s) {
    if (!s || !this.gl) return;
    // Same shared list the trace teardown uses: an overlay is a point-tier
    // clone of a trace and grows the same channel buffers.
    this._deleteBuffers(s, TRACE_GPU_BUFFERS);
  }

  // Full teardown of every sample overlay this tier owns. Overlays ride their
  // density cache entries (T9 pairing), so sweep the cache plus the aliased
  // references — an overlay can be reachable from several of them at once.
  _destroyDensitySample(g) {
    if (!g) return;
    g._sampleFadedOut = false;
    g._shownSampleOverlay = null;
    const owners = [...(g.densityCache || []),
      g.density, g.prevDensity, g._shownDensity, g._densitySwitchPrev, g._homeDensity];
    const seen = new Set();
    for (const d of owners) {
      const s = d && d.overlay;
      if (s && !seen.has(s)) { seen.add(s); this._destroySampleOverlay(s); }
      if (d) d.overlay = null;
    }
    if (g.sampleOverlay && !seen.has(g.sampleOverlay)) {
      this._destroySampleOverlay(g.sampleOverlay);
    }
    g.sampleOverlay = null;
  }

  // Build the overlay a sample-bearing reply shipped and attach it to the
  // density entry it was computed for (T9 pairing) — the draw path picks the
  // overlay of the best cached window for the view, so overlays for OTHER
  // windows (the home sample above all) stay alive and take over on zoom-out.
  // An explicit `sample: null` clears this window's overlay only.
  _applyDensitySample(g, sample, buffers) {
    if (!sample || !sample.x || !sample.y || sample.x.buf === undefined || sample.y.buf === undefined) {
      if (g.density) g.density.overlay = null;
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
      stroke: sample.stroke,
      channels: sample.channels,
    };
    const s: any = {
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
    const xValues = this._asF32(buffers[sample.x.buf]);
    const yValues = this._asF32(buffers[sample.y.buf]);
    s._cpu = { x: xValues, y: yValues, xMeta: s.xMeta, yMeta: s.yMeta };
    gl.bindBuffer(gl.ARRAY_BUFFER, s.xBuf);
    gl.bufferData(gl.ARRAY_BUFFER, xValues, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, s.yBuf);
    gl.bufferData(gl.ARRAY_BUFFER, yValues, gl.STATIC_DRAW);
    if (sample.color && sample.color.buf !== undefined) {
      s.colorMode = sample.color.mode === "continuous" ? 1 :
        (sample.color.mode === "categorical" ? 2 : 3);
      const colorValues = sample.color.dtype === "u8"
        ? this._asU8(buffers[sample.color.buf])
        : this._asF32(buffers[sample.color.buf]);
      if (s.colorMode === 3) s._cpu.rgba = colorValues;
      else s._cpu.color = colorValues;
      const colorBufferName = s.colorMode === 3 ? "rgbaBuf" : "cBuf";
      s[colorBufferName] = gl.createBuffer();
      this._tagChannelBuf(s[colorBufferName], colorValues, s.colorMode === 1);
      gl.bindBuffer(gl.ARRAY_BUFFER, s[colorBufferName]);
      gl.bufferData(gl.ARRAY_BUFFER, colorValues, gl.STATIC_DRAW);
      if (s.colorMode !== 3) {
        s.lut = sample.color.mode === "continuous"
          ? this._lut(sample.color.colormap)
          : this._paletteLut(sample.color.palette);
      }
    }
    if (sample.size && sample.size.mode === "continuous") {
      s.sizeMode = 1;
      const sizeValues = sample.size.dtype === "u8"
        ? this._asU8(buffers[sample.size.buf])
        : this._asF32(buffers[sample.size.buf]);
      s._cpu.size = sizeValues;
      s.sBuf = gl.createBuffer();
      this._tagChannelBuf(s.sBuf, sizeValues, true);
      gl.bindBuffer(gl.ARRAY_BUFFER, s.sBuf);
      gl.bufferData(gl.ARRAY_BUFFER, sizeValues, gl.STATIC_DRAW);
      s.sizeRange = sample.size.range_px;
    }
    const channel = (name) => sample.channels && sample.channels[name];
    const artistScalar = Number(trace.style && trace.style.artist_alpha);
    if (channel("opacity") || channel("artist_alpha") || channel("stroke_width") ||
        channel("symbol") || Number.isFinite(artistScalar)) {
      const values = new Float32Array(s.n * 4);
      for (let i = 0; i < s.n; i++) {
        values[i * 4] = 1;
        values[i * 4 + 1] = Number.isFinite(artistScalar) ? artistScalar : -1;
        values[i * 4 + 2] = -1;
        values[i * 4 + 3] = -1;
      }
      const copy = (name, component, scale = 1) => {
        const spec = channel(name);
        if (!spec) return;
        const source = spec.dtype === "u8"
          ? this._asU8(buffers[spec.buf])
          : this._asF32(buffers[spec.buf]);
        const components = spec.components || 1;
        for (let i = 0; i < s.n; i++) values[i * 4 + component] = source[i * components] * scale;
      };
      copy("opacity", 0);
      copy("artist_alpha", 1);
      copy("stroke_width", 2, this.dpr);
      copy("symbol", 3);
      s._cpuStyle = values;
      s.styleBuf = this._upload(values);
      // Overlays bake device-pixel widths like their parent trace, so they need
      // the same stamp for `_rescaleDprBakedBuffers` to find them.
      s._styleDpr = this.dpr;
    }
    if (sample.stroke && sample.stroke.mode === "direct_rgba") {
      s._cpuStroke = this._asU8(buffers[sample.stroke.buf]);
      s.strokeBuf = this._upload(s._cpuStroke);
    }
    this._pointMarkStyle(s, trace);
    if (g.density) {
      if (g.density.overlay && g.density.overlay !== g.sampleOverlay) {
        this._destroySampleOverlay(g.density.overlay);
      }
      g.density.overlay = s;
    }
    this._refreshReductionBadges();
  }

  // Draw the sample overlay belonging to the best cached window for the view
  // (T9 pairing, lodSampleForView): points on screen always describe the
  // window being displayed — a deep zoom-out falls back through the cache to
  // the home sample, so the full point cloud returns instead of a drilled
  // cluster lingering. Only a view no cached window covers draws a partial
  // overlay, bounded by the T9 coverage fade (overplot-compensated, so the
  // band value is what actually composites on screen — a fading sample must
  // LOOK faded). The "sampled n of N" badge tracks what is actually drawn.
  _drawDensitySample(g, x0, x1, y0, y1, opacityScale = 1) {
    const pick = lodSampleForView(this, g);
    const s = pick && pick.overlay;
    const changed = (g._shownSampleOverlay || null) !== (s || null);
    g._shownSampleOverlay = s || null;
    g._sampleFadedOut = !s;
    if (changed) this._refreshReductionBadges();
    if (!s) return;
    this._drawPoints(
      s,
      this._map(s.xMeta, x0, x1, s.xAxis),
      this._map(s.yMeta, y0, y1, s.yAxis),
      opacityScale * pick.alpha
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
    // Straight alpha: RECT_FS folds u_strokeOpacity and the per-item alpha
    // stack in and premultiplies there (uniform and buffer strokes alike).
    const sc = g.strokeColor || [0, 0, 0, 0];
    gl.uniform4f(u("u_stroke"), sc[0], sc[1], sc[2], sc[3]);
    gl.uniform1i(u("u_strokeMode"), g.strokeBuf ? 1 : (g.strokeMatchFill ? 2 : 0));
    gl.uniform1f(u("u_strokeOpacity"), this._strokeOpacity(g.trace.style || {}));
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
    g.strokeMatchFill = !!(t.stroke && t.stroke.mode === "match_fill");
    const opaque = [g.color[0], g.color[1], g.color[2], 1];
    g.strokeColor = s.stroke ? parseColor(this.root, s.stroke, opaque) : opaque;
    g.grad = this._resolveMarkFill(s, g.color);
  }

  // curve:"smooth" resample for the polyline marks. Returns null unless the
  // trace opted in and the data qualifies; hover keeps reading the original
  // `_cpu` columns either way (`_nearestCpuIndex` limits to the source length).
  _smoothArrays(t, x, y, base, n) {
    if (!t.style || t.style.curve !== "smooth") return null;
    // Polar draws chords, never smoothed curves: the Hermite control points
    // are only exact under an affine map, and both static exporters already
    // skip smoothing for the same reason (polar-axes.md §5). Resampling here
    // made the browser render a rounded shape the exports do not have.
    if (this.spec?.coords === "polar") return null;
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
    } else if (t.color && t.color.mode === "direct_rgba") {
      g.colorMode = 3;
      g.rgbaBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
    }
    this._buildInstanceStyleChannels(g, t, buffer, "width");
    g._cpu = { x: x0, y: y1, xMeta: g.x0Meta, yMeta: g.y1Meta };
  }

  // Flow bands (ribbon geometry contract). The six geometry columns reuse the
  // mesh attribute slots; the two paints ride a_rgba/a_rgba2. CPU copies are
  // retained for hover: picking is deferred (the id pass is point-geometry
  // only), so tooltips resolve by containment against the same cubic.
  _buildRibbonMark(g, t, buffer) {
    const names = [
      ["x0", "x0"], ["x1", "x1"], ["y0", "y0"], ["y1", "y1"],
      ["t0", "target_y0"], ["t1", "target_y1"],
    ];
    g._cpuRibbon = {};
    for (const [slot, key] of names) {
      const values = this._columnView(buffer, this.spec.columns[t[key]]);
      g[slot + "Meta"] = { ...this.spec.columns[t[key]] };
      g[slot + "Buf"] = this._upload(values);
      g._cpuRibbon[slot] = values;
      g.n = g.n === undefined ? values.length : Math.min(g.n, values.length);
    }
    g.color = parseColor(this.root, t.color && t.color.color, [0.3, 0.47, 0.66, 1]);
    if (t.color && t.color.mode === "direct_rgba") {
      g.rgbaBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
    }
    if (t.color_target && t.color_target.mode === "direct_rgba") {
      g.rgba2Buf = this._upload(
        this._columnView(buffer, this.spec.columns[t.color_target.buf]),
      );
    }
    g.colorTarget = t.color_target
      ? parseColor(this.root, t.color_target.color, g.color)
      : null;
    // Outline paint (ribbon geometry contract). An omitted stroke colour means
    // "match the band's own fill" — resolving it to g.color here would paint
    // every band of a per-band (direct_rgba) ribbon with the constant
    // fallback, which is not a colour the trace uses anywhere.
    const style = t.style || {};
    g.stroke = style.stroke ? parseColor(this.root, style.stroke, g.color) : null;
    g.strokeWidth = Number(style.stroke_width) || 0;
    g.tooltipRows = Array.isArray(t.tooltip_rows) ? t.tooltip_rows : null;
  }

  _drawRibbons(g, xm, ym) {
    if (g.n < 1) return;
    const gl = this.gl;
    const prog = this.ribbonProg;
    gl.useProgram(prog);
    const u = (n) => uniformOf(gl, prog, n);
    gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
    gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
    this._setAxisUniforms(prog, "u_x0", g.x0Meta, g.xAxis);
    this._setAxisUniforms(prog, "u_x1", g.x1Meta, g.xAxis);
    this._setAxisUniforms(prog, "u_y0", g.y0Meta, g.yAxis);
    this._setAxisUniforms(prog, "u_y1", g.y1Meta, g.yAxis);
    this._setAxisUniforms(prog, "u_t0", g.t0Meta, g.yAxis);
    this._setAxisUniforms(prog, "u_t1", g.t1Meta, g.yAxis);
    // RIBBON_VS reads the SHARED mode/constant uniforms (the RECT_VS design);
    // the per-column _setAxisUniforms calls above only cover the *meta pairs,
    // so without these four writes log/symlog axes silently render as linear.
    gl.uniform1i(u("u_xmode"), this._axisMode(g.xAxis));
    gl.uniform1f(u("u_xconstant"), this._axisConstant(g.xAxis));
    gl.uniform1i(u("u_ymode"), this._axisMode(g.yAxis));
    gl.uniform1f(u("u_yconstant"), this._axisConstant(g.yAxis));
    gl.uniform1i(u("u_segments"), RIBBON_STEPS);
    const transitionAlpha = (g._transitionOpacity ?? 1) * (g._legendDim ?? 1);
    gl.uniform1f(u("u_opacity"), this._fillOpacity(g.trace.style) * transitionAlpha);
    const stroke = g.stroke || [0, 0, 0, 0];
    gl.uniform4f(u("u_stroke"), stroke[0], stroke[1], stroke[2], stroke[3]);
    gl.uniform1i(u("u_strokeMode"), g.stroke ? 0 : 1);
    gl.uniform1f(u("u_strokeWidth"), (g.strokeWidth || 0) * this.dpr);
    gl.uniform1f(u("u_strokeOpacity"), this._strokeOpacity(g.trace.style || {}) * transitionAlpha);
    // A flat band must mix toward ITS OWN colour, so a per-band source buffer
    // with no target buffer binds the source buffer to both attributes —
    // mixing toward the constant fallback painted every node's right edge
    // with a colour from a different band.
    const rgba2Buf = g.rgba2Buf || g.rgbaBuf;
    const parts = ["x0", "x1", "y0", "y1", "t0", "t1"].map((name) => g[name + "Buf"]._fcId);
    parts.push(g.rgbaBuf ? g.rgbaBuf._fcId : 0, rgba2Buf ? rgba2Buf._fcId : 0);
    this._bindVao(g, "ribbon", parts, () => {
      this._vaoAttr(ATTR_SLOTS.ax0, g.x0Buf, 0, 1);
      this._vaoAttr(ATTR_SLOTS.ax1, g.x1Buf, 0, 1);
      this._vaoAttr(ATTR_SLOTS.ay0, g.y0Buf, 0, 1);
      this._vaoAttr(ATTR_SLOTS.ay1, g.y1Buf, 0, 1);
      this._vaoAttr(ATTR_SLOTS.ax2, g.t0Buf, 0, 1);
      this._vaoAttr(ATTR_SLOTS.ay2, g.t1Buf, 0, 1);
      if (g.rgbaBuf) this._vaoAttr(ATTR_SLOTS.a_rgba, g.rgbaBuf, 0, 1, 4, true);
      if (rgba2Buf) this._vaoAttr(ATTR_SLOTS.a_rgba2, rgba2Buf, 0, 1, 4, true);
    });
    if (!g.rgbaBuf) gl.vertexAttrib4f(ATTR_SLOTS.a_rgba, ...g.color);
    if (!rgba2Buf) gl.vertexAttrib4f(ATTR_SLOTS.a_rgba2, ...(g.colorTarget || g.color));
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 2 * (RIBBON_STEPS + 1), g.n);
  }

  // Containment test against the same cubic the shader sweeps: solve the
  // monotone bump curve for the cursor's x by bisection, then compare y with
  // the band's two edges at that parameter.
  _ribbonHover(g, dataX, dataY) {
    const cpu = g._cpuRibbon;
    if (!cpu) return null;
    // The cubic is normative in axis-transformed space (ribbon geometry
    // contract), so the pointer and every decoded endpoint go through the
    // same transform the shader's xyMap applies — solving in raw data space
    // would hit-test a curve the band does not follow on log/symlog axes.
    // On linear axes the transform is the identity. A masked-log NaN endpoint
    // fails every comparison and skips the band, matching the renderers.
    const xAxis = { ...this._axis(g.xAxis), constant: this._axisConstant(g.xAxis) };
    const yAxis = { ...this._axis(g.yAxis), constant: this._axisConstant(g.yAxis) };
    const pointerX = this._axisCoord(xAxis, dataX);
    const pointerY = this._axisCoord(yAxis, dataY);
    // _decodeValue already returns data space; decoding twice put every
    // containment test in a coordinate system nothing else uses.
    const val = (slot, index) => this._decodeValue(cpu[slot], g[slot + "Meta"], index);
    const xVal = (slot, index) => this._axisCoord(xAxis, val(slot, index));
    const yVal = (slot, index) => this._axisCoord(yAxis, val(slot, index));
    for (let index = 0; index < g.n; index++) {
      const x0 = xVal("x0", index);
      const x1 = xVal("x1", index);
      const lo0 = Math.min(x0, x1);
      const hi0 = Math.max(x0, x1);
      if (!(pointerX >= lo0 && pointerX <= hi0) || hi0 === lo0) continue;
      // x(t) is monotone between the faces (control points at the midpoint),
      // so 24 bisection steps pin t to ~1e-7 of the span.
      let a = 0.0;
      let b = 1.0;
      const xm = (x0 + x1) / 2;
      const xAt = (t) => {
        const uu = 1 - t;
        return uu * uu * uu * x0 + 3 * uu * uu * t * xm + 3 * uu * t * t * xm + t * t * t * x1;
      };
      const rising = x1 >= x0;
      for (let step = 0; step < 24; step++) {
        const mid = (a + b) / 2;
        if ((xAt(mid) < pointerX) === rising) a = mid; else b = mid;
      }
      const t = (a + b) / 2;
      const w0 = (1 - t) ** 3 + 3 * (1 - t) ** 2 * t;
      const w1 = 1 - w0;
      const edgeLo = w0 * yVal("y0", index) + w1 * yVal("t0", index);
      const edgeHi = w0 * yVal("y1", index) + w1 * yVal("t1", index);
      if (pointerY >= Math.min(edgeLo, edgeHi) && pointerY <= Math.max(edgeLo, edgeHi)) {
        return { trace: g.trace.id, index, g, dist: 0, synthetic: true };
      }
    }
    return null;
  }

  // Funnel ships one symmetric quad per stage (pos0/pos1 along the stage
  // axis, lo/hi cross edges at each end) plus a per-stage color channel. Each
  // column uploads as a per-instance attribute with ITS OWN meta uniform —
  // nothing is re-encoded client-side — and the funnel program sweeps a
  // 4-vertex strip per stage, sharing RIBBON_FS for the fwidth edge coverage
  // that keeps the slanted edges smooth on the antialias:false context.
  _buildFunnelMark(g, t, buffer) {
    const cols: any = {};
    const metas: any = {};
    let n = Infinity;
    for (const [name, slot] of Object.entries(FUNNEL_SLOTS)) {
      const values = this._columnView(buffer, this.spec.columns[t[name]]);
      cols[name] = values;
      metas[name] = { ...this.spec.columns[t[name]] };
      g[slot + "Meta"] = metas[name];
      g[slot + "Buf"] = this._upload(values);
      n = Math.min(n, values.length);
    }
    n = Number.isFinite(n) ? n : 0;
    g.n = n;
    g.orientation = t.orientation === "horizontal" ? 1 : 0;
    g._cpuFunnel = { ...cols, metas, n };
    // Stage centers for keyboard traversal (declared order): the a11y walk
    // reads g._cpu.x/y like any point group, so a funnel announces stage by
    // stage from the first. Centers are decoded to data space and re-encoded
    // against the pos0/lo0 metas the _cpu record carries.
    const posMeta = metas.pos0;
    const crossMeta = metas.lo0;
    const dec = (name, i) => this._decodeValue(cols[name], metas[name], i);
    const centerX = new Float32Array(n);
    const centerY = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const pCenter = (dec("pos0", i) + dec("pos1", i)) / 2;
      const cCenter = (dec("lo0", i) + dec("hi0", i) + dec("lo1", i) + dec("hi1", i)) / 4;
      const encP = (pCenter - posMeta.offset) * (posMeta.scale || 1);
      const encC = (cCenter - crossMeta.offset) * (crossMeta.scale || 1);
      centerX[i] = g.orientation === 1 ? encP : encC;
      centerY[i] = g.orientation === 1 ? encC : encP;
    }
    g._cpu = {
      x: centerX,
      y: centerY,
      xMeta: { ...(g.orientation === 1 ? posMeta : crossMeta) },
      yMeta: { ...(g.orientation === 1 ? crossMeta : posMeta) },
    };
    this._funnelPaint(g, t, buffer);
    const style = t.style || {};
    g.strokeWidth = Number(style.stroke_width) || 0;
    g.stroke = style.stroke ? parseColor(this.root, style.stroke, [0, 0, 0, 1]) : null;
    g.tooltipRows = Array.isArray(t.tooltip_rows) ? t.tooltip_rows : null;
  }

  // Per-stage fill resolved to one RGBA8 row per instance. Categorical codes
  // look their palette entry up here — theme-resolving each CSS color, so a
  // var(--…) palette entry follows light/dark — and the funnel program needs
  // no LUT texture. Build stashes codes+palette on the record; refreshColor
  // re-runs this with buffer=null to re-resolve against the new theme.
  _funnelPaint(g, t, buffer) {
    // Always resolved over the FULL stage count, never g.n: after a legend
    // filter g.n is the visible count, and a theme refresh that rebuilt the
    // cache at that length recolored the survivors by their DRAWN index and
    // lost the hidden stages' rows for good — restoring a stage then drew
    // garbage. The filter is applied at upload time instead.
    const full = g._cpuFunnel ? g._cpuFunnel.n : g.n;
    g.color = parseColor(this.root, t.color && t.color.color, [0.3, 0.47, 0.66, 1]);
    const channel = t.color || {};
    if (buffer !== null && Number.isInteger(channel.buf)) {
      if (channel.mode === "categorical") {
        g._funnelCodes = this._columnView(buffer, this.spec.columns[channel.buf]);
      } else if (channel.mode === "direct_rgba") {
        g._funnelRgba = this._columnView(buffer, this.spec.columns[channel.buf]);
      }
    }
    let rgba = null;
    if (channel.mode === "categorical" && g._funnelCodes) {
      const palette = Array.isArray(channel.palette) && channel.palette.length
        ? channel.palette : ["#4c78a8"];
      const table = palette.map((css) => parseColor(this.root, css, [0.3, 0.47, 0.66, 1]));
      rgba = new Uint8Array(full * 4);
      for (let i = 0; i < full; i++) {
        const c = table[Math.round(g._funnelCodes[i]) % table.length];
        rgba.set([c[0] * 255, c[1] * 255, c[2] * 255, c[3] * 255], i * 4);
      }
    } else if (channel.mode === "direct_rgba" && g._funnelRgba) {
      rgba = g._funnelRgba;
    }
    // Full-length rows kept for the legend filter and hover dim, which build
    // their visible/dimmed subsets from them rather than reading the GPU back.
    g._funnelRgbaFull = rgba || null;
    this._uploadFunnelPaint(g);
  }

  // Upload the paint rows the current legend filter leaves visible. The one
  // place rgbaBuf is (re)created, so a theme refresh, a filter toggle, and a
  // legend-hover dim can never disagree about row order.
  _uploadFunnelPaint(g, rows = null) {
    if (g.rgbaBuf) this._deleteBuffers(g, ["rgbaBuf"]);
    const full = rows || g._funnelRgbaFull;
    if (!full) return;
    let out = full;
    if (g._visMap) {
      out = new Uint8Array(g._visMap.length * 4);
      for (let k = 0; k < g._visMap.length; k++) {
        const i = g._visMap[k];
        out.set(full.subarray(i * 4, i * 4 + 4), k * 4);
      }
    }
    g.rgbaBuf = this._upload(out);
  }

  // Mix the six per-stage geometry columns for the current animation frame
  // and write them into the LIVE buffers in place (same WebGLBuffer objects,
  // so the VAO signature holds). Small-N by contract, so the per-frame CPU
  // mix is cheaper than a second attribute set and the shader stays as-is.
  // Covers the update interpolation (prev -> current by progress), the
  // enter grow (cross edges expand from the segment spine), and the settled
  // re-upload after either finishes.
  _mixFunnelGeometry(g) {
    const f = g._cpuFunnel;
    if (!f) return;
    const prev = g._transitionPrevFunnelValues;
    const progress = g._transitionPositionProgress;
    const grow = g._transitionGrow ?? 1;
    const mixing = (prev && Number.isFinite(progress) && progress < 1) || grow < 1;
    if (!mixing) {
      if (!g._funnelGeomMixed) return;
      delete g._funnelGeomMixed;
    }
    const gl = this.gl;
    const rows = g._visMap;
    const count = rows ? rows.length : f.n;
    const scratch = (g._funnelMixScratch ||= {});
    const mixed = {};
    for (const name of Object.keys(FUNNEL_SLOTS)) {
      const out = scratch[name] && scratch[name].length === count
        ? scratch[name]
        : (scratch[name] = new Float32Array(count));
      const cur = f[name];
      const start = prev && prev[name];
      for (let k = 0; k < count; k++) {
        const i = rows ? rows[k] : k;
        let value = cur[i];
        if (start && Number.isFinite(progress) && progress < 1) {
          value = start[i] + (value - start[i]) * progress;
        }
        out[k] = value;
      }
      mixed[name] = out;
    }
    if (grow < 1) {
      // Grow from the spine: both cross edges of each end expand from their
      // midpoint, so a vertical funnel widens out of its centerline exactly
      // as a bar grows out of its baseline. Encoded space is fine — the two
      // edges share a meta per column pair only after decoding, so mix the
      // DECODED midpoint per end via the metas.
      const dec = (name, values, index) => this._decodeValue(values, f.metas[name], index);
      const enc = (name, value) => (value - f.metas[name].offset) * (f.metas[name].scale || 1);
      for (let k = 0; k < count; k++) {
        for (const [lo, hi] of [["lo0", "hi0"], ["lo1", "hi1"]]) {
          const a = dec(lo, mixed[lo], k);
          const b = dec(hi, mixed[hi], k);
          const mid = (a + b) / 2;
          mixed[lo][k] = enc(lo, mid + (a - mid) * grow);
          mixed[hi][k] = enc(hi, mid + (b - mid) * grow);
        }
      }
    }
    for (const [name, slot] of Object.entries(FUNNEL_SLOTS)) {
      const buf = g[slot + "Buf"];
      if (!buf) continue;
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, mixed[name], gl.DYNAMIC_DRAW);
    }
    if (mixing) g._funnelGeomMixed = true;
  }

  _drawFunnels(g, xm, ym) {
    if (g.n < 1) return;
    const gl = this.gl;
    const prog = this.funnelProg;
    this._mixFunnelGeometry(g);
    gl.useProgram(prog);
    const u = (name) => uniformOf(gl, prog, name);
    const horizontal = g.orientation === 1;
    const posAxis = horizontal ? g.xAxis : g.yAxis;
    const crossAxis = horizontal ? g.yAxis : g.xAxis;
    gl.uniform2f(u("u_pmap"), ...(horizontal ? xm : ym));
    gl.uniform2f(u("u_cmap"), ...(horizontal ? ym : xm));
    this._setAxisUniforms(prog, "u_p0", g.x0Meta, posAxis);
    this._setAxisUniforms(prog, "u_p1", g.x1Meta, posAxis);
    this._setAxisUniforms(prog, "u_l0", g.y0Meta, crossAxis);
    this._setAxisUniforms(prog, "u_h0", g.y1Meta, crossAxis);
    this._setAxisUniforms(prog, "u_l1", g.x2Meta, crossAxis);
    this._setAxisUniforms(prog, "u_h1", g.y2Meta, crossAxis);
    gl.uniform1i(u("u_pmode"), this._axisMode(posAxis));
    gl.uniform1f(u("u_pconstant"), this._axisConstant(posAxis));
    gl.uniform1i(u("u_cmode"), this._axisMode(crossAxis));
    gl.uniform1f(u("u_cconstant"), this._axisConstant(crossAxis));
    gl.uniform1i(u("u_horizontal"), horizontal ? 1 : 0);
    const transitionAlpha = (g._transitionOpacity ?? 1) * (g._legendDim ?? 1);
    gl.uniform1f(u("u_opacity"), this._fillOpacity(g.trace.style) * transitionAlpha);
    const stroke = g.stroke || [0, 0, 0, 0];
    gl.uniform4f(u("u_stroke"), stroke[0], stroke[1], stroke[2], stroke[3]);
    gl.uniform1i(u("u_strokeMode"), g.stroke ? 0 : 1);
    gl.uniform1f(u("u_strokeWidth"), (g.strokeWidth || 0) * this.dpr);
    gl.uniform1f(u("u_strokeOpacity"), this._strokeOpacity(g.trace.style || {}) * transitionAlpha);
    const parts = Object.values(FUNNEL_SLOTS).map((slot) => g[slot + "Buf"]._fcId);
    parts.push(g.rgbaBuf ? g.rgbaBuf._fcId : 0);
    this._bindVao(g, "funnel", parts, () => {
      for (const slot of Object.values(FUNNEL_SLOTS)) {
        this._vaoAttr(ATTR_SLOTS["a" + slot], g[slot + "Buf"], 0, 1);
      }
      if (g.rgbaBuf) this._vaoAttr(ATTR_SLOTS.a_rgba, g.rgbaBuf, 0, 1, 4, true);
    });
    if (!g.rgbaBuf) gl.vertexAttrib4f(ATTR_SLOTS.a_rgba, ...g.color);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n);
  }

  // Containment against the same linear edges the mesh triangles draw, in
  // axis-transformed space (the ribbon rule: the pointer and the decoded
  // endpoints go through the transform the shader applies, so log/symlog
  // axes hit-test the drawn shape, and on linear axes it is the identity).
  // Index is the QUAD (= stage) index, which is what tooltip_rows and the
  // kernel exact-pick expect.
  _funnelHover(g, dataX, dataY) {
    const f = g._cpuFunnel;
    if (!f) return null;
    const horizontal = g.orientation === 1;
    const posAxis = horizontal ? g.xAxis : g.yAxis;
    const crossAxis = horizontal ? g.yAxis : g.xAxis;
    const posAxisRec = { ...this._axis(posAxis), constant: this._axisConstant(posAxis) };
    const crossAxisRec = { ...this._axis(crossAxis), constant: this._axisConstant(crossAxis) };
    const pointerPos = this._axisCoord(posAxisRec, horizontal ? dataX : dataY);
    const pointerCross = this._axisCoord(crossAxisRec, horizontal ? dataY : dataX);
    const val = (name, i) => this._decodeValue(f[name], f.metas[name], i);
    const posVal = (name, i) => this._axisCoord(posAxisRec, val(name, i));
    const crossVal = (name, i) => this._axisCoord(crossAxisRec, val(name, i));
    // A legend-hidden stage draws nothing, so it must not hover either; the
    // returned index stays the SHIPPED stage row, which is what tooltip_rows
    // and the kernel exact-pick speak.
    const rows = g._visMap ? Array.from(g._visMap) : null;
    for (let k = 0; k < (rows ? rows.length : f.n); k++) {
      const i = rows ? rows[k] : k;
      const p0 = posVal("pos0", i);
      const p1 = posVal("pos1", i);
      const lo = Math.min(p0, p1);
      const hi = Math.max(p0, p1);
      if (!(pointerPos >= lo && pointerPos <= hi) || hi === lo) continue;
      const t = (pointerPos - p0) / (p1 - p0);
      const eLo = crossVal("lo0", i) + (crossVal("lo1", i) - crossVal("lo0", i)) * t;
      const eHi = crossVal("hi0", i) + (crossVal("hi1", i) - crossVal("hi0", i)) * t;
      if (pointerCross >= Math.min(eLo, eHi) && pointerCross <= Math.max(eLo, eHi)) {
        return { trace: g.trace.id, index: i, g, dist: 0, synthetic: true };
      }
    }
    return null;
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
    } else if (t.color && t.color.mode === "direct_rgba") {
      g.colorMode = 3;
      g.rgbaBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
    }
    this._buildInstanceStyleChannels(g, t, buffer, "stroke_width");
    const style = t.style || {};
    g.meshStrokeWidth = Number(style.stroke_width) || 0;
    g.meshStroke = parseColor(this.root, style.stroke || "transparent", [0, 0, 0, 0]);
    g.strokeMatchFill = !!(t.stroke && t.stroke.mode === "match_fill");
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
    const parts: any = {};
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
    } else if (t.color && t.color.mode === "direct_rgba") {
      g.colorMode = 3;
      g.rgbaBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
    }
    this._buildInstanceStyleChannels(g, t, buffer, "stroke_width");
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
    g._cpuBar = {
      pos,
      value1: v1,
      value0: g._cpuValue0 || null,
      posMeta: g.posMeta,
      value1Meta: g.value1Meta,
      value0Meta: g.value0Meta || null,
      value0Const: g.value0Const,
      width: g.width,
    };
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
    } else if (t.color && t.color.mode === "direct_rgba") {
      g.colorMode = 3;
      g.rgbaBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
    }
    this._buildInstanceStyleChannels(g, t, buffer, "stroke_width");
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

  _uploadGrid(f32, w, h, maxVal, rgba = null, filter = "linear", pointAlpha = 1) {
    const gl = this.gl;
    const tex = gl.createTexture();
    lodWriteGridTexture(gl, tex, f32, w, h, maxVal, rgba, filter, pointAlpha);
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
    if (meta.dtype === "u32") return new Uint32Array(span.buffer, absoluteOffset, length);
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
  _vaoAttr(slot, buf, byteOffset, divisor, size = 1, normalized = false) {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.enableVertexAttribArray(slot);
    gl.vertexAttribPointer(
      slot, size, buf._fcType || gl.FLOAT, normalized || !!buf._fcNormalized, 0, byteOffset,
    );
    gl.vertexAttribDivisor(slot, divisor);
  }

  // Tag a (re)uploaded per-point channel buffer with its element type. u8
  // uploads of unit-scalar channels (continuous color/size, density_val) bind
  // normalized so the shader keeps seeing [0,1]; categorical codes stay
  // un-normalized (the shader addresses palette texels with the raw code).
  // Any pointer-config change — dtype OR normalization — re-ids the buffer so
  // a VAO holding the old configuration rebuilds instead of silently
  // misreading the bytes. Normalization can flip with the dtype unchanged: a
  // reused cBuf crossing categorical (u8 codes, un-normalized) ↔ continuous
  // (u8 coordinates, normalized) keeps UNSIGNED_BYTE both ways.
  _tagChannelBuf(buf, values, normalized) {
    const gl = this.gl;
    const type = values instanceof Uint8Array ? gl.UNSIGNED_BYTE : gl.FLOAT;
    const isNormalized = !!normalized && type === gl.UNSIGNED_BYTE;
    if (
      buf._fcType !== undefined &&
      (buf._fcType !== type || buf._fcNormalized !== isNormalized)
    ) {
      buf._fcId = ++this._bufSeq;
    }
    buf._fcType = type;
    buf._fcNormalized = isNormalized;
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
    gl.uniform1f(u(`${prefix}constant`), this._axisConstant(axisId));
  }

  // Widest angular span, in the theta axis's own data units, across a
  // four-edge-column trace. Cached on the trace: it is a property of the data,
  // not of the view, so it survives pan/zoom and cannot make the subdivision
  // count view-dependent (§28). Rebuilt traces get a fresh object and re-measure.
  _polarRectMaxSpan(g) {
    if (g._polarMaxSpan !== undefined) return g._polarMaxSpan;
    const cpu = g._cpuRect;
    // No CPU copy to measure (a path that does not retain one) means fall back
    // to the full-turn count rather than guess narrow.
    let widest = cpu ? 0 : NaN;
    if (cpu) {
      for (let i = 0; i < g.n; i++) {
        const span = this._decodeValue(cpu.x1, cpu.x1Meta, i)
          - this._decodeValue(cpu.x0, cpu.x0Meta, i);
        if (Number.isFinite(span)) widest = Math.max(widest, Math.abs(span));
      }
    }
    g._polarMaxSpan = widest;
    return widest;
  }

  // Geometry of the polar disc, in the units the shaders and the CPU-side
  // hover math both need. Null on a cartesian chart.
  //
  // The GL canvas is sized and positioned to exactly the plot rect, so clip
  // space [-1,1] IS the plot rect. Full turns center there; partial sectors fit
  // their visible bounding box and can move the polar origin. Radius therefore
  // converts to clip units per axis (2R/w, 2R/h) — a vec2, because a round
  // circle in a non-square rect cannot use one scalar.
  _polarGeometry() {
    if (this.spec?.coords !== "polar") return null;
    const p = this.plot;
    if (!p || !(p.w > 0) || !(p.h > 0)) return null;
    const thetaAxis = this._axis("x") || {};
    const radialAxis = this._axis("y") || {};
    const rawZero = thetaAxis.theta_zero ?? "E";
    const zero = typeof rawZero === "string" ? (THETA_ZERO[rawZero] ?? 0) : Number(rawZero) || 0;
    const dir = thetaAxis.theta_direction === "clockwise" ? -1 : 1;
    const unitScale = thetaAxis.theta_unit === "degrees" ? Math.PI / 180 : 1;
    const angularTurn = thetaAxis.theta_unit === "degrees" ? 360 : 2 * Math.PI;
    const authoredSector = Array.isArray(thetaAxis.sector) && thetaAxis.sector.length === 2
      ? [Number(thetaAxis.sector[0]), Number(thetaAxis.sector[1])]
      : [0, angularTurn];
    const sectorStart = Number.isFinite(authoredSector[0]) ? authoredSector[0] : 0;
    const sectorEnd = Number.isFinite(authoredSector[1]) ? authoredSector[1] : angularTurn;
    const sectorSpan = Math.max(0, sectorEnd - sectorStart);
    const fullSector = sectorSpan >= angularTurn * (1 - 1e-10);
    const categories = thetaAxis.kind === "category" ? (thetaAxis.categories || []) : null;
    const categoryCount = categories ? categories.length : 0;
    let thetaStart = sectorStart;
    let thetaEnd = sectorEnd;
    let dirUnit = dir * unitScale;
    let angleBase = zero;
    if (categories) {
      // Full turns are N equal bands with no duplicated seam. Partial sectors
      // instead place the first and last category centers on the authored
      // endpoints, hence N-1 intervals.
      const intervals = fullSector
        ? Math.max(categoryCount, 1)
        : Math.max(categoryCount - 1, 1);
      dirUnit = dir * unitScale * sectorSpan / intervals;
      angleBase = zero + dir * unitScale * sectorStart;
      thetaStart = 0;
      thetaEnd = fullSector ? Math.max(categoryCount, 1) : Math.max(categoryCount - 1, 0);
    }
    const dataTurn = (2 * Math.PI) / Math.max(Math.abs(dirUnit), 1e-30);
    const [rLoRaw, rHiRaw] = this._axisRange("y");
    const rLo = this._axisCoord(radialAxis, rLoRaw);
    const rHi = this._axisCoord(radialAxis, rHiRaw);
    const originRaw = radialAxis.r_origin != null && Number.isFinite(Number(radialAxis.r_origin))
      ? Number(radialAxis.r_origin)
      : Number(rLoRaw);
    const rOrigin = this._axisCoord(radialAxis, originRaw);
    const hole = Math.max(0, Math.min(0.999999, Number(radialAxis.hole) || 0));
    const angleStart = zero + dir * unitScale * sectorStart;
    const angleEnd = zero + dir * unitScale * sectorEnd;
    let radius;
    let cx;
    let cy;
    if (fullSector) {
      radius = Math.min(p.w, p.h) / 2;
      cx = p.x + p.w / 2;
      cy = p.y + p.h / 2;
    } else {
      // Fit the sector's actual bounding box, including its visible inner
      // boundary. A semicircular gauge should use the whole plot instead of
      // reserving an invisible half-disc.
      const denom = rHi - rOrigin;
      const inner = Math.max(0, Math.min(1, Math.abs(denom) > 1e-30
        ? hole + (1 - hole) * ((rLo - rOrigin) / denom)
        : 0));
      const loAngle = Math.min(angleStart, angleEnd);
      const hiAngle = Math.max(angleStart, angleEnd);
      const angles = [angleStart, angleEnd];
      for (const cardinal of [0, Math.PI / 2, Math.PI, 3 * Math.PI / 2]) {
        const first = Math.ceil((loAngle - cardinal) / (2 * Math.PI));
        const last = Math.floor((hiAngle - cardinal) / (2 * Math.PI));
        for (let turnIndex = first; turnIndex <= last; turnIndex++) {
          angles.push(cardinal + turnIndex * 2 * Math.PI);
        }
      }
      const xs = [];
      const ys = [];
      for (const angle of angles) {
        xs.push(Math.cos(angle), inner * Math.cos(angle));
        ys.push(-Math.sin(angle), -inner * Math.sin(angle));
      }
      if (inner <= 1e-12) {
        xs.push(0);
        ys.push(0);
      }
      const xmin = Math.min(...xs);
      const xmax = Math.max(...xs);
      const ymin = Math.min(...ys);
      const ymax = Math.max(...ys);
      const xspan = Math.max(xmax - xmin, 1e-12);
      const yspan = Math.max(ymax - ymin, 1e-12);
      radius = Math.min(p.w / xspan, p.h / yspan);
      const left = p.x + (p.w - radius * xspan) / 2;
      const top = p.y + (p.h - radius * yspan) / 2;
      cx = left - radius * xmin;
      cy = top - radius * ymin;
    }
    return {
      radius,
      cx,
      cy,
      clipCx: ((cx - p.x) / p.w) * 2 - 1,
      clipCy: 1 - ((cy - p.y) / p.h) * 2,
      clipRx: (2 * radius) / p.w,
      clipRy: (2 * radius) / p.h,
      rLo,
      rHi,
      rLoRaw,
      rHiRaw,
      rOrigin,
      rOriginRaw: originRaw,
      hole,
      zero: angleBase,
      rawZero: zero,
      dir,
      dirUnit,
      unitScale,
      turn: dataTurn,
      angularTurn,
      thetaStart,
      thetaEnd,
      sectorStart,
      sectorEnd,
      sectorSpan,
      fullSector,
      angleStart,
      angleEnd,
      categoryCount,
      gridShape: thetaAxis.grid_shape || "circular",
    };
  }

  _polarPositiveMod(value, period) {
    return ((value % period) + period) % period;
  }

  _polarThetaValue(geom, angle) {
    const raw = (angle - geom.zero) / (geom.dirUnit || 1);
    return geom.thetaStart
      + this._polarPositiveMod(raw - geom.thetaStart, geom.turn || 1);
  }

  _polarThetaVisible(geom, theta) {
    const sweep = geom.thetaEnd - geom.thetaStart;
    if (sweep >= geom.turn * (1 - 1e-10)) return true;
    const offset = this._polarPositiveMod(theta - geom.thetaStart, geom.turn || 1);
    return offset <= sweep + geom.turn * 1e-10;
  }

  _polarThetaAngle(geom, theta) {
    return geom.zero + geom.dirUnit * theta;
  }

  _polarRadius(geom, value, { coord = false } = {}) {
    const radial = coord ? Number(value) : this._axisCoord(this._axis("y"), value);
    const denom = geom.rHi - geom.rOrigin;
    if (!Number.isFinite(radial) || !Number.isFinite(denom) || Math.abs(denom) <= 1e-30) {
      return NaN;
    }
    const fraction = geom.hole
      + (1 - geom.hole) * ((radial - geom.rOrigin) / denom);
    return fraction * geom.radius;
  }

  _polarProjectCoords(thetaCoord, rCoord, geom) {
    if (!geom || !this._polarThetaVisible(geom, thetaCoord)) return [NaN, NaN];
    const rMin = Math.min(geom.rLo, geom.rHi);
    const rMax = Math.max(geom.rLo, geom.rHi);
    if (!Number.isFinite(rCoord) || rCoord < rMin - 1e-10 || rCoord > rMax + 1e-10) {
      return [NaN, NaN];
    }
    const projectedRadius = this._polarRadius(geom, rCoord, { coord: true });
    if (!Number.isFinite(projectedRadius)
        || projectedRadius < geom.hole * geom.radius - 1e-6
        || projectedRadius > geom.radius + 1e-6) return [NaN, NaN];
    const angle = this._polarThetaAngle(geom, thetaCoord);
    return [
      geom.cx + projectedRadius * Math.cos(angle),
      geom.cy - projectedRadius * Math.sin(angle),
    ];
  }

  _polarProject(theta, radius, geom = this._polarGeometry()) {
    return this._polarProjectCoords(
      this._axisCoord(this._axis("x"), theta),
      this._axisCoord(this._axis("y"), radius),
      geom,
    );
  }

  _projectDataPoint(xAxisId, yAxisId, x, y, geom = this._polarGeometry()) {
    if (geom) return this._polarProject(x, y, geom);
    return [this._dataPx(xAxisId, x), this._dataPx(yAxisId, y)];
  }

  _projectSegmentEndpoints(g, cpu, index, geom = this._polarGeometry()) {
    const theta0 = this._decodeValue(cpu.x0, g.x0Meta, index);
    const theta1 = this._decodeValue(cpu.x1, g.x1Meta, index);
    const radial0 = this._decodeValue(cpu.y0, g.y0Meta, index);
    const radial1 = this._decodeValue(cpu.y1, g.y1Meta, index);
    if (!geom) {
      return [
        this._projectDataPoint(g.xAxis, g.yAxis, theta0, radial0, null),
        this._projectDataPoint(g.xAxis, g.yAxis, theta1, radial1, null),
      ];
    }
    const thetaAxis = this._axis("x");
    const radialAxis = this._axis("y");
    const th0 = this._axisCoord(thetaAxis, theta0);
    const th1 = this._axisCoord(thetaAxis, theta1);
    const r0 = this._axisCoord(radialAxis, radial0);
    const r1 = this._axisCoord(radialAxis, radial1);
    const rMin = Math.min(geom.rLo, geom.rHi);
    const rMax = Math.max(geom.rLo, geom.rHi);
    if (Math.max(r0, r1) < rMin || Math.min(r0, r1) > rMax) {
      return [[NaN, NaN], [NaN, NaN]];
    }
    const dr = r1 - r0;
    let t0 = 0;
    let t1 = 1;
    if (Math.abs(dr) > 1e-30) {
      const ta = (rMin - r0) / dr;
      const tb = (rMax - r0) / dr;
      t0 = Math.max(0, Math.min(ta, tb));
      t1 = Math.min(1, Math.max(ta, tb));
    }
    return [
      this._polarProjectCoords(
        th0 + (th1 - th0) * t0,
        Math.max(rMin, Math.min(rMax, r0 + dr * t0)),
        geom,
      ),
      this._polarProjectCoords(
        th0 + (th1 - th0) * t1,
        Math.max(rMin, Math.min(rMax, r0 + dr * t1)),
        geom,
      ),
    ];
  }

  // Concentric rings for radial ticks and spokes for angular ticks. Partial
  // sectors get radial edges; `grid_shape="linear"` connects spoke
  // intersections into polygon rings instead of drawing circular arcs.
  _drawPolarGrid(ctx, geom, thetaTicks, rTicks, thetaAxis, rAxis, hideTheta, hideR) {
    const sweep = geom.thetaEnd - geom.thetaStart;
    const full = sweep >= geom.turn * (1 - 1e-10);
    const angularOffset = (value) => this._polarPositiveMod(
      value - geom.thetaStart,
      geom.turn || 1,
    );
    const thetaValues = [...thetaTicks, ...(full ? [] : [geom.thetaStart, geom.thetaEnd])]
      .filter((value) => Number.isFinite(value) && this._polarThetaVisible(geom, value))
      .sort((a, b) => angularOffset(a) - angularOffset(b))
      .filter((value, index, values) => (
        index === 0 || Math.abs(angularOffset(value) - angularOffset(values[index - 1])) > 1e-10
      ));
    if (full && thetaValues.length > 1) {
      const first = angularOffset(thetaValues[0]);
      const last = angularOffset(thetaValues[thetaValues.length - 1]);
      if (Math.abs((last - first) - geom.turn) <= geom.turn * 1e-10) thetaValues.pop();
    }
    const angles = thetaValues.map((value) => this._polarThetaAngle(geom, value));
    const point = (angle, radius) => [
      geom.cx + radius * Math.cos(angle),
      geom.cy - radius * Math.sin(angle),
    ];
    const ringPath = (radius) => {
      if (!(radius > 0) || radius > geom.radius + 1e-6) return;
      if (geom.gridShape === "linear" && angles.length >= (full ? 3 : 2)) {
        const [x0, y0] = point(angles[0], radius);
        ctx.moveTo(x0, y0);
        for (let i = 1; i < angles.length; i++) {
          const [x, y] = point(angles[i], radius);
          ctx.lineTo(x, y);
        }
        if (full) ctx.closePath();
        return;
      }
      if (full) {
        ctx.moveTo(geom.cx + radius, geom.cy);
        ctx.arc(geom.cx, geom.cy, radius, 0, Math.PI * 2);
      } else {
        const start = this._polarThetaAngle(geom, geom.thetaStart);
        const end = this._polarThetaAngle(geom, geom.thetaEnd);
        const [x, y] = point(start, radius);
        ctx.moveTo(x, y);
        ctx.arc(geom.cx, geom.cy, radius, -start, -end, geom.dir > 0);
      }
    };
    if (!hideR) {
      ctx.strokeStyle = this._axisStylePaint(rAxis, "grid_color", this.theme.grid);
      ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(rAxis, "grid_width", 1));
      ctx.globalAlpha = this._axisStyleNumber(rAxis, "grid_opacity", 1);
      ctx.setLineDash(this._axisGridDash(rAxis));
      ctx.beginPath();
      for (const v of rTicks) {
        ringPath(this._polarRadius(geom, v));
      }
      ctx.stroke();
    }
    if (hideTheta) return;
    ctx.strokeStyle = this._axisStylePaint(thetaAxis, "grid_color", this.theme.grid);
    ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(thetaAxis, "grid_width", 1));
    ctx.globalAlpha = this._axisStyleNumber(thetaAxis, "grid_opacity", 1);
    ctx.setLineDash(this._axisGridDash(thetaAxis));
    ctx.beginPath();
    const innerRadius = Math.max(
      0,
      Math.min(geom.radius, this._polarRadius(geom, geom.rLo, { coord: true })),
    );
    for (const a of angles) {
      const [x0, y0] = point(a, innerRadius);
      const [x1, y1] = point(a, geom.radius);
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
    }
    ctx.stroke();
    // Polar spines cannot be represented by the cartesian DIV spines.
    ctx.strokeStyle = this._axisStylePaint(thetaAxis, "axis_color", this.theme.axis);
    ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(thetaAxis, "axis_width", 1));
    ctx.globalAlpha = 1;
    ctx.setLineDash([]);
    ctx.beginPath();
    ringPath(geom.radius);
    if (innerRadius > 1e-6) ringPath(innerRadius);
    if (!full && angles.length >= 2) {
      for (const a of [angles[0], angles[angles.length - 1]]) {
        const [x0, y0] = point(a, innerRadius);
        const [x1, y1] = point(a, geom.radius);
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y1);
      }
    }
    ctx.stroke();
  }

  _setPolarUniforms(prog) {
    const gl = this.gl;
    const u = (n) => uniformOf(gl, prog, n);
    // Fragment-stage polar clipping uses device-pixel gl_FragCoord, including
    // in the pick framebuffer. Programs without the clip helper optimize this
    // uniform away; WebGL treats the resulting null location as a no-op.
    gl.uniform2f(u("u_clipRes"), this.canvas.width, this.canvas.height);
    const g = this._polarGeometry();
    if (!g) {
      gl.uniform1i(u("u_coordMode"), 0);
      return;
    }
    gl.uniform1i(u("u_coordMode"), 1);
    gl.uniform4f(u("u_polar"), g.clipCx, g.clipCy, g.clipRx, g.clipRy);
    gl.uniform2f(u("u_rrange"), g.rLo, g.rHi);
    gl.uniform2f(u("u_zdir"), g.zero, g.dirUnit);
    gl.uniform2f(u("u_trange"), g.thetaStart, g.thetaEnd);
    gl.uniform1f(u("u_turn"), g.turn);
    gl.uniform2f(u("u_rshape"), g.rOrigin, g.hole);
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


  _renderGlFrame() {
    this._healStaleTheme();
    // `_drawPoints` records authored-marker draws here so the Canvas overlay
    // paints the exact direct/sample/drill entries and LOD alpha chosen by
    // this frame.  Reconstructing them from gpuTraces would lose density
    // window selection and transition fades.
    this._authoredScatterDraws = [];
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

    const drawTrace = (g) => {
      if (g._legendHidden) return; // legend click-toggle (interaction spec §10)
      if (g.tier === "density") {
        // Tier frame (drill/fades/cache) lives in 45_lod.js — chart-agnostic.
        const [gx0, gx1] = this._axisRange(g.xAxis);
        const [gy0, gy1] = this._axisRange(g.yAxis);
        lodDrawDensityTier(this, g, gx0, gx1, gy0, gy1);
        return;
      }
      if (g.tier === "decimated" && g._decimatedRefined && g._homeDecimated) {
        const r = g._decimatedWindow;
        // _axisRange preserves axis direction (a reversed axis yields
        // hi-before-lo) while the served window arrives normalized, so the
        // coverage compare runs on normalized bounds.
        const [vx0, vx1] = this._axisRange(g.xAxis);
        const viewLo = Math.min(vx0, vx1);
        const viewHi = Math.max(vx0, vx1);
        const eps = r ? Math.abs(r[1] - r[0]) * 1e-9 + 1e-300 : 0;
        // A prior refined window is not a truthful covering representation
        // after a pan/zoom leaves it.  Draw the retained overview until the
        // pending reply installs a buffer covering this view (T1/T8).
        if (!r || viewLo < r[0] - eps || viewHi > r[1] + eps) {
          markOf(g.trace.kind).draw(this, g._homeDecimated, x0, x1, y0, y1);
          return;
        }
      }
      markOf(g.trace.kind).draw(this, g, x0, x1, y0, y1);
    };
    for (const g of this._transitionOldTraces || []) drawTrace(g);
    for (const g of this.gpuTraces) {
      drawTrace(g);
    }
    this._drawHoverState();
  }

  _drawNow() {
    if (this._destroyed || !this.gl || this._glLost) return;
    let rendered;
    if (this._glHost) {
      rendered = this._glHost.render(
        this,
        this._present2d,
        this.canvas.width,
        this.canvas.height,
        () => this._renderGlFrame(),
      );
    } else {
      rendered = this._renderGlFrame();
    }
    // Presentation now owns the GL pixels. Do DOM/2D overlay work afterward
    // so the shared default framebuffer is copied immediately after GPU work.
    // Keep a visible tooltip anchored through pan, zoom, and linked views.
    this._repositionTooltip();
    // Hover-only frames leave the pick snapshot valid (see draw()); direct
    // _drawNow() callers never set the flag, so they invalidate as before.
    if (!this._rafKeepPick) this._pickDirty = true;
    this._rafKeepPick = false;
    this._drawChrome();
    this._renderLassoSelection?.();
    this._renderBoxSelection?.();
    return rendered;
  }

  // Centralized clock seam for animation state machines. Production uses the
  // browser's monotonic clock; deterministic render probes can replace this
  // private method without relying on platform-specific writability of
  // performance.now.
  _now() {
    return performance.now();
  }

  // Resolve scatter emphasis entirely from resident view state.  The deepest
  // of the two axis zooms drives emphasis, so x-only and y-only zooms both
  // activate it. Interpolation is linear in log zoom, not screen space.
  _pointZoomStyle(g) {
    const style = g.trace?.style || {};
    const baseOpacity = this._fillOpacity(style, 0.8);
    const baseStrokeOpacity = this._strokeOpacity(style, 0.8);
    const targetSizeFactor = Number(style.zoom_size_factor) || 1;
    const targetOpacity = style.zoom_opacity === undefined
      ? baseOpacity
      : Math.max(0, Math.min(1, Number(style.zoom_opacity)));
    const emphasis = Number(style.zoom_emphasis) || 16;
    if ((targetSizeFactor === 1 && targetOpacity === baseOpacity) || emphasis <= 1) {
      return { sizeFactor: 1, opacity: baseOpacity, strokeOpacity: baseStrokeOpacity };
    }
    const axisZoom = (axisId) => {
      const axis = this._axis(axisId);
      const [lo, hi] = this._axisRange(axisId);
      const [homeLo, homeHi] = this._axisRange(axisId, this.view0);
      const span = Math.abs(this._axisCoord(axis, hi) - this._axisCoord(axis, lo));
      const homeSpan = Math.abs(
        this._axisCoord(axis, homeHi) - this._axisCoord(axis, homeLo)
      );
      return Number.isFinite(span) && span > 0 && Number.isFinite(homeSpan) && homeSpan > 0
        ? homeSpan / span
        : null;
    };
    // Zoom against the trace's own axes: a scatter on x2/y2 must respond to
    // its axes, not the primary view ranges.
    const zoom = Math.max(axisZoom(g.xAxis || "x") ?? 1, axisZoom(g.yAxis || "y") ?? 1);
    const t = Math.max(0, Math.min(1, Math.log(Math.max(1, zoom)) / Math.log(emphasis)));
    // zoom_opacity is a shared target: strokes interpolate from their own
    // stroke_opacity base toward it in step with the fill.
    const targetStrokeOpacity =
      style.zoom_opacity === undefined ? baseStrokeOpacity : targetOpacity;
    return {
      sizeFactor: 1 + (targetSizeFactor - 1) * t,
      opacity: baseOpacity + (targetOpacity - baseOpacity) * t,
      strokeOpacity: baseStrokeOpacity + (targetStrokeOpacity - baseStrokeOpacity) * t,
    };
  }


  _canDrawSimplePoints(g) {
    return g.colorMode === 0 && g.sizeMode === 0 && !g.selActive &&
      !g.rgbaBuf && !g.styleBuf && !g.strokeBuf &&
      (g.symbol || 0) === 0 && (g.pointStrokeWidth || 0) <= 0 &&
      Math.max(g.lodBlendShown ?? 0, g.lodBlend ?? 0) <= 0.001;
  }

  _drawPoints(g, xm, ym, opacityScale = 1) {
    opacityScale *= (g._transitionOpacity ?? 1) * (g._legendDim ?? 1);
    // Pyplot-authored contours and glyphs keep these resident point buffers
    // for picking/transitions but paint on the Canvas2D overlay below. Queue
    // the actual draw invocation (including density-sample/drill fades)
    // instead of rediscovering only top-level direct traces in `_drawChrome`.
    if (g.authoredMarker) {
      (this._authoredScatterDraws ||= []).push({ g, opacityScale });
      return;
    }
    const animationScale = g._transitionScale ?? 1;
    if (this._canDrawSimplePoints(g)) {
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
    this._setPolarUniforms(prog);
    gl.uniform1f(u("u_dpr"), this.dpr);
    const zoomStyle = this._pointZoomStyle(g);
    const transitionOn = !!(g._transitionPrevXBuf && g._transitionPrevYBuf);
    gl.uniform1i(u("u_transitionActive"), transitionOn ? 1 : 0);
    gl.uniform1f(u("u_transitionProgress"), g._transitionPositionProgress ?? 1);
    gl.uniform1f(u("u_size"), g.size * animationScale * zoomStyle.sizeFactor);
    gl.uniform1i(u("u_sizeMode"), g.sizeMode);
    gl.uniform2f(u("u_sizeRange"),
      g.sizeRange[0] * animationScale * zoomStyle.sizeFactor,
      g.sizeRange[1] * animationScale * zoomStyle.sizeFactor);
    gl.uniform1i(u("u_colorMode"), g.colorMode);
    const markOpacity = zoomStyle.opacity * opacityScale;
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
    const [r, gg, b, a] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, a);
    gl.uniform1i(u("u_symbol"), g.symbol || 0);
    const sc = g.pointStroke;
    gl.uniform1f(u("u_ptStrokeWidth"), (g.pointStrokeWidth || 0) * this.dpr);
    gl.uniform1i(u("u_ptStrokeFace"), g.pointStrokeFace ? 1 : 0);
    gl.uniform1i(u("u_strokeMode"), g.strokeBuf ? 1 : 0);
    gl.uniform1f(u("u_strokeOpacity"), zoomStyle.strokeOpacity * opacityScale);
    // Straight alpha: POINT_FS folds u_strokeOpacity and the per-item alpha
    // stack in and premultiplies there (uniform and buffer strokes alike).
    gl.uniform4f(u("u_ptStroke"), sc ? sc[0] : 0, sc ? sc[1] : 0,
      sc ? sc[2] : 0, sc ? sc[3] : 0);

    gl.uniform1i(u("u_selActive"), g.selActive ? 1 : 0);
    const colorOn = g.colorMode !== 0 && g.cBuf;
    const sizeOn = g.sizeMode === 1 && g.sBuf;
    const selOn = g.selActive && g.selBuf;
    const rgbaOn = g.colorMode === 3 && g.rgbaBuf;
    const styleOn = !!g.styleBuf;
    const strokeOn = !!g.strokeBuf;
    if (g.lut) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, g.lut);
      gl.uniform1i(u("u_lut"), 0);
    }
    // Drill handoff (§5): blend from the aggregate's local count-alpha toward
    // native opacity (hue already matches — the texture wears the mean point
    // color, LOD doc §2). The shown weight eases toward the kernel's target
    // so successive drill updates re-weight smoothly instead of stepping.
    // Time-based decay (τ=90ms) — a per-frame factor would converge 2.4×
    // faster on a 144Hz display.
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
    const blendOn = blend > 0.001 && g.dBuf;

    this._bindVao(
      g,
      "points",
      [
        g.xBuf._fcId, g.yBuf._fcId,
        colorOn ? g.cBuf._fcId : 0,
        sizeOn ? g.sBuf._fcId : 0,
        selOn ? g.selBuf._fcId : 0,
        blendOn ? g.dBuf._fcId : 0,
        transitionOn ? g._transitionPrevXBuf._fcId : 0,
        transitionOn ? g._transitionPrevYBuf._fcId : 0,
        rgbaOn ? g.rgbaBuf._fcId : 0,
        styleOn ? g.styleBuf._fcId : 0,
        strokeOn ? g.strokeBuf._fcId : 0,
      ],
      () => {
        this._vaoAttr(ATTR_SLOTS.ax, g.xBuf, 0, 0);
        this._vaoAttr(ATTR_SLOTS.ay, g.yBuf, 0, 0);
        if (colorOn) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 0);
        if (sizeOn) this._vaoAttr(ATTR_SLOTS.a_sval, g.sBuf, 0, 0);
        if (selOn) this._vaoAttr(ATTR_SLOTS.a_sel, g.selBuf, 0, 0);
        if (blendOn) this._vaoAttr(ATTR_SLOTS.a_dval, g.dBuf, 0, 0);
        if (transitionOn) {
          this._vaoAttr(ATTR_SLOTS.a_prevx, g._transitionPrevXBuf, 0, 0);
          this._vaoAttr(ATTR_SLOTS.a_prevy, g._transitionPrevYBuf, 0, 0);
        }
        if (rgbaOn) this._vaoAttr(ATTR_SLOTS.a_rgba, g.rgbaBuf, 0, 0, 4, true);
        if (styleOn) this._vaoAttr(ATTR_SLOTS.a_style, g.styleBuf, 0, 0, 4);
        if (strokeOn) this._vaoAttr(ATTR_SLOTS.a_stroke, g.strokeBuf, 0, 0, 4, true);
      }
    );
    // Generic (constant) attribute values are context state, not VAO state —
    // set the disabled channels' fallbacks each draw (no driver lookups).
    if (!colorOn) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
    if (!sizeOn) gl.vertexAttrib1f(ATTR_SLOTS.a_sval, 0.5);
    if (!selOn) gl.vertexAttrib1f(ATTR_SLOTS.a_sel, 1.0);
    if (!blendOn) gl.vertexAttrib1f(ATTR_SLOTS.a_dval, 0);
    if (!rgbaOn) gl.vertexAttrib4f(ATTR_SLOTS.a_rgba, r, gg, b, a);
    if (!styleOn) gl.vertexAttrib4f(ATTR_SLOTS.a_style, 1, -1, -1, -1);
    if (!strokeOn) gl.vertexAttrib4f(ATTR_SLOTS.a_stroke, r, gg, b, a);
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
    this._setPolarUniforms(prog);
    gl.uniform1f(u("u_dpr"), this.dpr);
    const zoomStyle = this._pointZoomStyle(g);
    const transitionOn = !!(g._transitionPrevXBuf && g._transitionPrevYBuf);
    gl.uniform1i(u("u_transitionActive"), transitionOn ? 1 : 0);
    gl.uniform1f(u("u_transitionProgress"), g._transitionPositionProgress ?? 1);
    gl.uniform1f(u("u_size"), g.size * (g._transitionScale ?? 1) * zoomStyle.sizeFactor);
    const [r, gg, b, a] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, a * zoomStyle.opacity * opacityScale);
    this._bindVao(
      g,
      "points-simple",
      [g.xBuf._fcId, g.yBuf._fcId,
        transitionOn ? g._transitionPrevXBuf._fcId : 0,
        transitionOn ? g._transitionPrevYBuf._fcId : 0],
      () => {
        this._vaoAttr(ATTR_SLOTS.ax, g.xBuf, 0, 0);
        this._vaoAttr(ATTR_SLOTS.ay, g.yBuf, 0, 0);
        if (transitionOn) {
          this._vaoAttr(ATTR_SLOTS.a_prevx, g._transitionPrevXBuf, 0, 0);
          this._vaoAttr(ATTR_SLOTS.a_prevy, g._transitionPrevYBuf, 0, 0);
        }
      }
    );
    gl.drawArrays(gl.POINTS, 0, g.n);
  }

  _drawHoverState() {
    const hit = this._hoverTarget;
    if (!hit || !hit.g) return;
    const g = hit.g;
    if (g.trace.kind !== "scatter" || g.tier === "density" || g._legendHidden) return;
    // Filtered buffers are addressed by the drawn index, not the shipped one.
    const index = hit.drawIndex ?? hit.index;
    if (!Number.isInteger(index) || index < 0 || index >= g.n) return;
    const [x0, x1] = this._axisRange(g.xAxis);
    const [y0, y1] = this._axisRange(g.yAxis);
    this._drawHoverPoint(
      g,
      index,
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
    this._setPolarUniforms(prog);
    // Size-channel points hover at their encoded size, not the scalar default
    // (sample traces keep no CPU copy of the size column; they fall back).
    const sVal = g.sizeMode === 1 && g._cpu?.size ? g._cpu.size[index] : null;
    const baseSize = sVal != null && Number.isFinite(sVal)
      ? g.sizeRange[0] + (g.sizeRange[1] - g.sizeRange[0]) * sVal
      : (g.size || 4);
    const adjustedSize = baseSize * this._pointZoomStyle(g).sizeFactor;
    const defaultSize = Math.max(adjustedSize * 1.75, adjustedSize + 5);
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
    const d = density || g.density;
    // Structural guard: never bind a freed texture. Eviction pins every live
    // density (lodDensityPinned), so this should not trigger — but a crossfade
    // holds its source across frames, and binding a deleted handle is a hard
    // WebGL error that aborts the draw, so treat an invalid texture as "nothing
    // to draw" rather than risk it.
    if (!d || !d.tex || !gl.isTexture(d.tex)) return;
    opacityScale *= (g._transitionOpacity ?? 1) * (g._legendDim ?? 1);
    const prog = this.densityProg;
    gl.useProgram(prog);
    const u = (n) => uniformOf(gl, prog, n);
    const { x0, x1, y0, y1 } = this.view;
    const [vx0, vx1] = this._axisRange(g.xAxis);
    const [vy0, vy1] = this._axisRange(g.yAxis);
    gl.uniform4f(u("u_view"), vx0 ?? x0, vx1 ?? x1, vy0 ?? y0, vy1 ?? y1);
    gl.uniform1i(u("u_xmode"), this._axisMode(g.xAxis));
    gl.uniform1f(u("u_xconstant"), this._axisConstant(g.xAxis));
    gl.uniform1i(u("u_ymode"), this._axisMode(g.yAxis));
    gl.uniform1f(u("u_yconstant"), this._axisConstant(g.yAxis));
    // Density grids are uniform in scale coordinates (§28): the shader's uv
    // is an affine map of the interpolated coordinate, so the grid range
    // ships to the GPU already transformed (f64 here, cheap — 4 scalars).
    const xAxis = this._axis(g.xAxis), yAxis = this._axis(g.yAxis);
    gl.uniform4f(
      u("u_gridRange"),
      this._axisCoord(xAxis, d.xRange[0]), this._axisCoord(xAxis, d.xRange[1]),
      this._axisCoord(yAxis, d.yRange[0]), this._axisCoord(yAxis, d.yRange[1]),
    );
    // Mean-color textures bake the style opacity INSIDE their physical
    // compositing (LOD doc §2 rule 1 — dense cells saturate past it exactly
    // like overplotted marks), so the uniform carries only the transition
    // fades for them; count-only grids keep style opacity here as before.
    gl.uniform1f(
      u("u_opacity"),
      (d.rgba ? 1 : this._fillOpacity(g.trace.style)) * opacityScale,
    );
    // Mean-color grids carry their colors in the texture (LOD doc §2);
    // count-only grids tint with the constant trace color or, failing that,
    // fall back to the LUT ramp (hand-built/legacy specs).
    gl.uniform1i(u("u_meanColor"), d.rgba ? 1 : 0);
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
    gl.uniform1f(u("u_xconstant"), this._axisConstant(g.xAxis));
    gl.uniform1i(u("u_ymode"), this._axisMode(g.yAxis));
    gl.uniform1f(u("u_yconstant"), this._axisConstant(g.yAxis));
    this._setPolarUniforms(prog);
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
    gl.uniform1f(u("u_opacity"), this._fillOpacity(g.trace.style) * (g._transitionOpacity ?? 1) * (g._legendDim ?? 1));
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
    this._setPolarUniforms(this.lineProg);
    gl.uniform2f(u("u_res"), this.canvas.width, this.canvas.height);
    const transitionOn = !!(g._transitionPrevXBuf && g._transitionPrevYBuf);
    gl.uniform1i(u("u_transitionActive"), transitionOn ? 1 : 0);
    gl.uniform1f(u("u_transitionProgress"), g._transitionPositionProgress ?? 1);
    const reveal = Math.max(0, Math.min(1, g._transitionReveal ?? 1));
    gl.uniform1f(u("u_revealProgress"), reveal);
    gl.uniform1f(u("u_revealSegments"), g.n - 1);
    const lineWidth = (width ?? g.trace.style.width ?? 1.5) * this.dpr;
    gl.uniform1f(u("u_width"), lineWidth);
    // Absent cap/join keys mean XY's default, which is round for both — the
    // trace only carries them when they differ from it (marks._stroke_geometry).
    const cap = LINE_CAP_MODES[g.trace.style.linecap] ?? LINE_CAP_MODES.round;
    gl.uniform1i(u("u_cap"), cap);
    const [r, gg, b, a] = color || g.color;
    const strokeOpacity = this._strokeOpacity(g.trace.style) * (opacity ?? 1) * (g._transitionOpacity ?? 1) * (g._legendDim ?? 1);
    gl.uniform4f(u("u_color"), r, gg, b, a * strokeOpacity);
    const dashed = this._lineDash(g);
    this._bindVao(
      g,
      "line",
      [g.xBuf._fcId, g.yBuf._fcId, dashed ? g._lenBuf._fcId : 0,
        transitionOn ? g._transitionPrevXBuf._fcId : 0,
        transitionOn ? g._transitionPrevYBuf._fcId : 0],
      () => {
        this._vaoAttr(ATTR_SLOTS.ax0, g.xBuf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ax1, g.xBuf, 4, 1);
        this._vaoAttr(ATTR_SLOTS.ay0, g.yBuf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ay1, g.yBuf, 4, 1);
        if (dashed) {
          this._vaoAttr(ATTR_SLOTS.a_len0, g._lenBuf, 0, 1);
          this._vaoAttr(ATTR_SLOTS.a_len1, g._lenBuf, 4, 1);
        }
        if (transitionOn) {
          this._vaoAttr(ATTR_SLOTS.a_prevx, g._transitionPrevXBuf, 0, 1);
          this._vaoAttr(ATTR_SLOTS.a_prevy, g._transitionPrevYBuf, 0, 1);
          this._vaoAttr(ATTR_SLOTS.a_prevx1, g._transitionPrevXBuf, 4, 1);
          this._vaoAttr(ATTR_SLOTS.a_prevy1, g._transitionPrevYBuf, 4, 1);
        }
      }
    );
    const segments = Math.max(0, Math.min(g.n - 1, Math.ceil((g.n - 1) * reveal)));
    gl.uniform1i(u("u_capSegments"), segments);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, segments);
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
    this._setPolarUniforms(prog);
    gl.uniform2f(u("u_res"), this.canvas.width, this.canvas.height);
    gl.uniform1f(u("u_width"), (g.trace.style.width ?? 1.5) * this.dpr);
    gl.uniform1f(u("u_animationProgress"), g._transitionScale ?? 1);
    const [r, gg, b, a] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, a);
    gl.uniform1f(u("u_opacity"), this._strokeOpacity(g.trace.style) * (g._transitionOpacity ?? 1) * (g._legendDim ?? 1));
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
        g.colorMode && g.cBuf ? g.cBuf._fcId : 0,
        g.rgbaBuf ? g.rgbaBuf._fcId : 0,
        g.styleBuf ? g.styleBuf._fcId : 0,
        dashed ? g._segmentDashOffsetBuf._fcId : 0,
        dashed ? g._segmentDashDirBuf._fcId : 0],
      () => {
        this._vaoAttr(ATTR_SLOTS.ax0, g.x0Buf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ax1, g.x1Buf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ay0, g.y0Buf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ay1, g.y1Buf, 0, 1);
        if (g.colorMode && g.cBuf) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 1);
        if (g.rgbaBuf) this._vaoAttr(ATTR_SLOTS.a_rgba, g.rgbaBuf, 0, 1, 4, true);
        if (g.styleBuf) this._vaoAttr(ATTR_SLOTS.a_style, g.styleBuf, 0, 1, 4);
        if (dashed) {
          this._vaoAttr(ATTR_SLOTS.a_dash0, g._segmentDashOffsetBuf, 0, 1);
          this._vaoAttr(ATTR_SLOTS.a_dashDir, g._segmentDashDirBuf, 0, 1);
        }
      }
    );
    if (!g.cBuf) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
    if (!g.rgbaBuf) gl.vertexAttrib4f(ATTR_SLOTS.a_rgba, r, gg, b, a);
    if (!g.styleBuf) gl.vertexAttrib4f(ATTR_SLOTS.a_style, 1, -1, -1, -1);
    const count = Math.max(0, Math.min(g.n, Math.ceil(g.n * (g._transitionReveal ?? 1))));
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, count);
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
    const polarGeom = this._polarGeometry();
    for (let i = 0; i < n; i++) {
      const [[x0, y0], [x1, y1]] = this._projectSegmentEndpoints(g, cpu, i, polarGeom);
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
    gl.uniform1f(u("u_opacity"), this._fillOpacity(g.trace.style) * (g._legendDim ?? 1));
    gl.uniform4f(u("u_color"), g.color[0], g.color[1], g.color[2], g.color[3]);
    // Straight alpha: MESH_FS folds u_strokeOpacity and the per-item alpha
    // stack in and premultiplies there (uniform and buffer strokes alike).
    const stroke = g.meshStroke || [0, 0, 0, 0];
    gl.uniform4f(u("u_stroke"), stroke[0], stroke[1], stroke[2], stroke[3]);
    gl.uniform1f(u("u_strokeWidth"), g.meshStrokeWidth || 0);
    gl.uniform1i(u("u_strokeMode"), g.strokeBuf ? 1 : (g.strokeMatchFill ? 2 : 0));
    gl.uniform1f(u("u_strokeOpacity"), this._strokeOpacity(g.trace.style) * (g._legendDim ?? 1));
    if (g.colorMode && g.lut) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, g.lut);
      gl.uniform1i(u("u_lut"), 0);
    }
    const parts = ["x0", "x1", "x2", "y0", "y1", "y2"].map((name) => g[name + "Buf"]._fcId);
    parts.push(g.cBuf ? g.cBuf._fcId : 0, g.rgbaBuf ? g.rgbaBuf._fcId : 0,
      g.styleBuf ? g.styleBuf._fcId : 0, g.strokeBuf ? g.strokeBuf._fcId : 0);
    this._bindVao(g, "mesh", parts, () => {
      for (const name of ["x0", "x1", "x2", "y0", "y1", "y2"]) {
        this._vaoAttr(ATTR_SLOTS["a" + name], g[name + "Buf"], 0, 1);
      }
      if (g.cBuf) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 1);
      if (g.rgbaBuf) this._vaoAttr(ATTR_SLOTS.a_rgba, g.rgbaBuf, 0, 1, 4, true);
      if (g.styleBuf) this._vaoAttr(ATTR_SLOTS.a_style, g.styleBuf, 0, 1, 4);
      if (g.strokeBuf) this._vaoAttr(ATTR_SLOTS.a_stroke, g.strokeBuf, 0, 1, 4, true);
    });
    if (!g.cBuf) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
    if (!g.rgbaBuf) gl.vertexAttrib4f(ATTR_SLOTS.a_rgba, ...g.color);
    if (!g.styleBuf) gl.vertexAttrib4f(ATTR_SLOTS.a_style, 1, -1, -1, -1);
    if (!g.strokeBuf) gl.vertexAttrib4f(ATTR_SLOTS.a_stroke, ...stroke);
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
    const polarGeom = this._polarGeometry();
    let [px, py] = this._projectDataPoint(
      g.xAxis,
      g.yAxis,
      this._decodeValue(g._dashX, g.xMeta, 0),
      this._decodeValue(g._dashY, g.yMeta, 0),
      polarGeom,
    );
    let acc = 0;
    lens[0] = 0;
    for (let i = 1; i < n; i++) {
      const [nx, ny] = this._projectDataPoint(
        g.xAxis,
        g.yAxis,
        this._decodeValue(g._dashX, g.xMeta, i),
        this._decodeValue(g._dashY, g.yMeta, i),
        polarGeom,
      );
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
    this._setPolarUniforms(prog);
    this._setAxisUniforms(prog, "u_b", g.baseMeta, g.yAxis);
    const reveal = Math.max(0, Math.min(1, g._transitionReveal ?? 1));
    gl.uniform1f(u("u_revealProgress"), reveal);
    gl.uniform1f(u("u_revealSegments"), g.n - 1);
    const [r, gg, b, a] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, a * this._fillOpacity(g.trace.style, 0.35) * (g._transitionOpacity ?? 1) * (g._legendDim ?? 1));
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
    const count = Math.max(0, Math.min(g.n - 1, Math.ceil((g.n - 1) * reveal)));
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, count);
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
    gl.uniform1f(u("u_xconstant"), this._axisConstant(g.xAxis));
    gl.uniform1i(u("u_ymode"), this._axisMode(g.yAxis));
    gl.uniform1f(u("u_yconstant"), this._axisConstant(g.yAxis));
    gl.uniform4f(u("u_edgePad"), edgePad[0], edgePad[1], edgePad[2], edgePad[3]);
    // Four edge columns are an annular sector under polar — this is the path
    // unequal-width slices (a pie or donut) take, since the compact bar path
    // ships one scalar width.
    this._setPolarUniforms(prog);
    const [r, gg, b, a] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, a);
    gl.uniform1f(u("u_opacity"), this._fillOpacity(g.trace.style) * (g._transitionOpacity ?? 1) * (g._legendDim ?? 1));
    gl.uniform1i(u("u_colorMode"), g.colorMode || 0);
    this._setRectStyleUniforms(prog, g);
    const colorOn = !!g.cBuf;
    const rgbaOn = !!g.rgbaBuf;
    const styleOn = !!g.styleBuf;
    const strokeOn = !!g.strokeBuf;
    const radiusOn = !!g.radiusBuf;
    if (colorOn) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, g.lut);
      gl.uniform1i(u("u_lut"), 0);
    }
    this._bindVao(
      g,
      "rects",
      [g.x0Buf._fcId, g.x1Buf._fcId, g.y0Buf._fcId, g.y1Buf._fcId,
        colorOn ? g.cBuf._fcId : 0, rgbaOn ? g.rgbaBuf._fcId : 0,
        styleOn ? g.styleBuf._fcId : 0, strokeOn ? g.strokeBuf._fcId : 0,
        radiusOn ? g.radiusBuf._fcId : 0],
      () => {
        this._vaoAttr(ATTR_SLOTS.ax0, g.x0Buf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ax1, g.x1Buf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ay0, g.y0Buf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.ay1, g.y1Buf, 0, 1);
        if (colorOn) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 1);
        if (rgbaOn) this._vaoAttr(ATTR_SLOTS.a_rgba, g.rgbaBuf, 0, 1, 4, true);
        if (styleOn) this._vaoAttr(ATTR_SLOTS.a_style, g.styleBuf, 0, 1, 4);
        if (strokeOn) this._vaoAttr(ATTR_SLOTS.a_stroke, g.strokeBuf, 0, 1, 4, true);
        if (radiusOn) this._vaoAttr(ATTR_SLOTS.a_radius, g.radiusBuf, 0, 1, 2);
      }
    );
    if (!colorOn) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
    if (!rgbaOn) gl.vertexAttrib4f(ATTR_SLOTS.a_rgba, r, gg, b, a);
    if (!styleOn) gl.vertexAttrib4f(ATTR_SLOTS.a_style, 1, -1, -1, -1);
    if (!strokeOn) gl.vertexAttrib4f(ATTR_SLOTS.a_stroke, ...(g.strokeColor || g.color));
    if (!radiusOn) gl.vertexAttrib2f(ATTR_SLOTS.a_radius, -1, -1);
    // Unequal widths ship four edge columns, so one instanced draw covers wedges
    // of different sweeps: the count follows the WIDEST of them (recorded once at
    // build time, from data alone), which keeps every narrower wedge inside the
    // same flattening bound. A pie's widest slice sets the cost for the pie.
    const rectGeom = this._polarGeometry();
    const rectPolarSegments = rectGeom
      ? xyPolarBarSegments(this._polarRectMaxSpan(g) * rectGeom.dirUnit, 2 * Math.PI)
      : 0;
    if (rectPolarSegments) {
      gl.uniform1f(u("u_wedgeGap"), (Number(g.trace.style?.wedge_gap) || 0) * this.dpr);
      gl.uniform1i(u("u_polarSegments"), rectPolarSegments);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 2 * (rectPolarSegments + 1), g.n);
    } else {
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n);
    }
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
    // Bars name their axes u_p/u_v rather than u_x/u_y, so they need this
    // explicitly — without it u_coordMode stays 0 and a polar bar chart draws
    // cartesian rectangles inside correct polar chrome.
    this._setPolarUniforms(prog);
    gl.uniform1i(u("u_pmode"), this._axisMode(pAxis));
    gl.uniform1f(u("u_pconstant"), this._axisConstant(pAxis));
    gl.uniform1i(u("u_vmode"), this._axisMode(vAxis));
    gl.uniform1f(u("u_vconstant"), this._axisConstant(vAxis));
    gl.uniform1f(u("u_width"), g.width);
    gl.uniform1i(u("u_orientation"), g.orientation);
    gl.uniform1i(u("u_v0Mode"), g.value0Mode);
    gl.uniform1f(u("u_v0Const"), v0Const ?? 0);
    gl.uniform1f(u("u_v0EdgePad"), v0EdgePad);
    gl.uniform1f(u("u_animationProgress"), g._transitionGrow ?? 1);
    const transitionOn = !!(
      g._transitionPrevPosBuf &&
      g._transitionPrevValue1Buf &&
      g._transitionPrevValue0Buf
    );
    gl.uniform1i(u("u_transitionActive"), transitionOn ? 1 : 0);
    gl.uniform1f(u("u_transitionProgress"), g._transitionPositionProgress ?? 1);
    gl.uniform1f(u("u_prevWidth"), g._transitionPrevWidth ?? g.width);
    const [r, gg, b, a] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, a);
    gl.uniform1f(u("u_opacity"), this._fillOpacity(g.trace.style) * (g._transitionOpacity ?? 1) * (g._legendDim ?? 1));
    gl.uniform1i(u("u_colorMode"), g.colorMode || 0);
    this._setRectStyleUniforms(prog, g);
    const v0On = g.value0Mode === 1 && g.value0Buf;
    const colorOn = !!g.cBuf;
    const rgbaOn = !!g.rgbaBuf;
    const styleOn = !!g.styleBuf;
    const strokeOn = !!g.strokeBuf;
    const radiusOn = !!g.radiusBuf;
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
        transitionOn ? g._transitionPrevPosBuf._fcId : 0,
        transitionOn ? g._transitionPrevValue1Buf._fcId : 0,
        transitionOn ? g._transitionPrevValue0Buf._fcId : 0,
        rgbaOn ? g.rgbaBuf._fcId : 0,
        styleOn ? g.styleBuf._fcId : 0,
        strokeOn ? g.strokeBuf._fcId : 0,
        radiusOn ? g.radiusBuf._fcId : 0,
      ],
      () => {
        this._vaoAttr(ATTR_SLOTS.a_pos, g.posBuf, 0, 1);
        this._vaoAttr(ATTR_SLOTS.a_v1, g.value1Buf, 0, 1);
        if (v0On) this._vaoAttr(ATTR_SLOTS.a_v0, g.value0Buf, 0, 1);
        if (colorOn) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 1);
        if (transitionOn) {
          this._vaoAttr(ATTR_SLOTS.a_prevx, g._transitionPrevPosBuf, 0, 1);
          this._vaoAttr(ATTR_SLOTS.a_prevy, g._transitionPrevValue1Buf, 0, 1);
          this._vaoAttr(ATTR_SLOTS.a_prevx1, g._transitionPrevValue0Buf, 0, 1);
        }
        if (rgbaOn) this._vaoAttr(ATTR_SLOTS.a_rgba, g.rgbaBuf, 0, 1, 4, true);
        if (styleOn) this._vaoAttr(ATTR_SLOTS.a_style, g.styleBuf, 0, 1, 4);
        if (strokeOn) this._vaoAttr(ATTR_SLOTS.a_stroke, g.strokeBuf, 0, 1, 4, true);
        if (radiusOn) this._vaoAttr(ATTR_SLOTS.a_radius, g.radiusBuf, 0, 1, 2);
      }
    );
    if (!v0On) gl.vertexAttrib1f(ATTR_SLOTS.a_v0, 0);
    if (!colorOn) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
    if (!rgbaOn) gl.vertexAttrib4f(ATTR_SLOTS.a_rgba, r, gg, b, a);
    if (!styleOn) gl.vertexAttrib4f(ATTR_SLOTS.a_style, 1, -1, -1, -1);
    if (!strokeOn) gl.vertexAttrib4f(ATTR_SLOTS.a_stroke, ...(g.strokeColor || g.color));
    if (!radiusOn) gl.vertexAttrib2f(ATTR_SLOTS.a_radius, -1, -1);
    // A polar bar sweeps an annular sector: segments+1 vertex PAIRS instead of
    // one quad's four corners. The count follows this trace's own angular width
    // (xyPolarBarSegments) rather than the full-turn worst case, at the same
    // flattening bound — a 22.5-degree wind-rose sector costs 14 vertices, not
    // 194. The compact bar path carries ONE scalar width, so the whole instanced
    // draw shares one honest count.
    const barGeom = this._polarGeometry();
    const polarSegments = barGeom
      ? xyPolarBarSegments(Number(g.width) * barGeom.dirUnit, 2 * Math.PI)
      : 0;
    if (polarSegments) {
      gl.uniform1f(u("u_wedgeGap"), (Number(g.trace.style?.wedge_gap) || 0) * this.dpr);
      gl.uniform1i(u("u_polarSegments"), polarSegments);
      const vAxisId = g.orientation === 1 ? g.xAxis : g.yAxis;
      gl.uniform1f(u("u_polarV0C"), this._axisCoord(this._axis(vAxisId), g.value0Const ?? 0));
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 2 * (polarSegments + 1), g.n);
    } else {
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n);
    }
  }

  _dataPxX(value) {
    return this._dataPx("x", value);
  }

  _dataPxY(value) {
    return this._dataPx("y", value);
  }

  // A point-anchored (theta, r) pair in canvas px. The separable _dataPxX /
  // _dataPxY pair cannot express polar placement: it reads (0, 0) — the disc
  // centre, at any angle — as the bottom-left corner, and strings a set of
  // labels out in a horizontal row in theta order. Mirrors the `point()`
  // helper in `_annotation_svg` and the `marker` branch of
  // `annotation_label_placement` (python/xy/_svg.py), which the two exporters
  // already share; without this the browser and the exports disagree about
  // where every annotation on a polar chart belongs.
  //
  // Point-anchored kinds only. `rule` and `band` are genuinely different
  // geometry on a disc (a theta rule is a spoke, an r rule is a ring) and stay
  // deferred on the cartesian path, exactly as they do in the exporters.
  _dataPxPoint(x, y, xAxisId = "x", yAxisId = "y") {
    return this._projectDataPoint(
      xAxisId,
      yAxisId,
      Number(x),
      Number(y),
      this._polarGeometry(),
    );
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
    return ["auto", "hide", "rotate", "stagger", "preserve", "none", "off"].includes(value)
      ? value : "auto";
  }

  _axisDefaultSide(axis) {
    const id = String(axis && axis.id || "x");
    if (id.startsWith("x")) return "bottom";
    return id === "y" ? "left" : "right";
  }

  _axisTickSides(axis) {
    const isX = String(axis && axis.id || "x").startsWith("x");
    const allowed = isX ? ["bottom", "top"] : ["left", "right"];
    if (!Array.isArray(axis && axis.tick_sides)) {
      return [axis && axis.side || this._axisDefaultSide(axis)];
    }
    return allowed.filter((side) => axis.tick_sides.includes(side));
  }

  _axisTickLabelSides(axis) {
    const isX = String(axis && axis.id || "x").startsWith("x");
    const allowed = isX ? ["bottom", "top"] : ["left", "right"];
    if (!Array.isArray(axis && axis.tick_label_sides)) {
      return [axis && axis.side || this._axisDefaultSide(axis)];
    }
    return allowed.filter((side) => axis.tick_label_sides.includes(side));
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

  // `maxWidth` word-wraps the block before measuring, so `h` is the height the
  // wrapped text actually occupies. Mirrors `_textblock.measure(max_width=...)`
  // in python/xy/_textblock.py, including the wrap rule in `xyWrapLines`.
  _estimateTickLabel(text, fontSize, maxWidth = null) {
    let lines = String(text ?? "").replace(/\r\n?/g, "\n").split("\n");
    const context = typeof document !== "undefined"
      ? (
        this._tickMeasureCanvas
        || (this._tickMeasureCanvas = document.createElement("canvas"))
      ).getContext("2d")
      : null;
    // Match the root's default font shorthand in 20_theme.ts. Measuring with
    // the browser's generic sans-serif while the DOM paints system-ui can
    // under-reserve long y labels enough to consume the title's 0.4 em gap.
    if (context) context.font = `${fontSize}px system-ui, sans-serif`;
    const advance = (line) =>
      context?.measureText(line).width || xyTextAdvance(line, fontSize);
    const limit = Number(maxWidth);
    if (Number.isFinite(limit) && limit > 0) lines = xyWrapLines(lines, advance, limit);
    return {
      lines,
      w: Math.max(fontSize * 0.7, ...lines.map(advance)),
      h: Math.max(fontSize * 1.2, lines.length * fontSize * 1.2),
      lineStep: fontSize * 1.2,
    };
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
    if (strategyValue === "preserve") return withBase;
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
      return { css: "white-space:pre-line;text-align:center;", style: rawPosition };
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
          "transform-origin:center;white-space:pre-line;text-align:center;",
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
        "transform-origin:center;white-space:pre-line;text-align:center;",
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
    // Tick labels are DOM: `this.labels` is emptied and every label, baseline
    // and tick div is recreated. A view animation throttles that to 80 ms
    // because the ranges are moving. A DATA animation was not throttled at all,
    // so an entrance or update transition rebuilt the whole label layer 60 times
    // a second while the axes stood still — the labels are identical between
    // those frames unless `_transitionView` is also interpolating the view, and
    // that case is covered by the same cadence. The final frame runs with
    // `_dataAnim` already cleared, so the settled labels always land.
    const labelCadenceMs = (this._viewAnim || this._dataAnim) ? 80 : 0;
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
    const extraXAxes = Object.values<any>(this.axes).filter((axis: any) =>
      axis && axis.id !== "x" && String(axis.id || "").startsWith("x"));
    const extraYAxes = Object.values<any>(this.axes).filter((axis: any) =>
      axis && axis.id !== "y" && String(axis.id || "").startsWith("y"));
    const hideX = this._axisTickLabelStrategy(xAxis) === "none";
    const hideY = this._axisTickLabelStrategy(yAxis) === "none";
    const xt = this._axisTicks(
      "x",
      this._axisTickTarget("x", Math.max(3, p.w / (xAxis.kind === "time" ? 90 : 80))),
    );
    const yt = this._axisTicks("y", this._axisTickTarget("y", Math.max(3, p.h / 45)));
    const minorTicks = (axis, axisId) => {
      if (!Array.isArray(axis.minor_tick_values)) return [];
      const [lo, hi] = this._axisRange(axisId);
      const a = Math.min(lo, hi), b = Math.max(lo, hi);
      return axis.minor_tick_values.map(Number)
        .filter((v) => Number.isFinite(v) && v >= a && v <= b);
    };
    const xmt = minorTicks(xAxis, "x");
    const ymt = minorTicks(yAxis, "y");
    const minorAxis = (axis) => ({ ...axis, style: axis.minor_style || {} });
    const xmAxis = minorAxis(xAxis);
    const ymAxis = minorAxis(yAxis);
    const xEdge = (px) => Math.min(p.x + p.w - 0.5, Math.max(p.x + 0.5, Math.round(px) + 0.5));
    const yEdge = (py) => Math.min(p.y + p.h - 0.5, Math.max(p.y + 0.5, Math.round(py) + 0.5));

    const polarGeom = this._polarGeometry();
    if (polarGeom) {
      this._drawPolarGrid(ctx, polarGeom, xt.ticks, yt.ticks, xAxis, yAxis, hideX, hideY);
    }
    ctx.strokeStyle = this._axisStylePaint(xmAxis, "grid_color", "transparent");
    ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(xmAxis, "grid_width", 1));
    ctx.globalAlpha = this._axisStyleNumber(xmAxis, "grid_opacity", 1);
    ctx.setLineDash(this._axisGridDash(xmAxis));
    ctx.beginPath();
    for (const v of (hideX || polarGeom ? [] : xmt)) {
      const px = this._dataPx("x", v);
      if (!Number.isFinite(px)) continue;
      const x = xEdge(px);
      ctx.moveTo(x, p.y);
      ctx.lineTo(x, p.y + p.h);
    }
    ctx.stroke();

    ctx.strokeStyle = this._axisStylePaint(ymAxis, "grid_color", "transparent");
    ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(ymAxis, "grid_width", 1));
    ctx.globalAlpha = this._axisStyleNumber(ymAxis, "grid_opacity", 1);
    ctx.setLineDash(this._axisGridDash(ymAxis));
    ctx.beginPath();
    for (const v of (hideY || polarGeom ? [] : ymt)) {
      const py = this._dataPx("y", v);
      if (!Number.isFinite(py)) continue;
      const y = yEdge(py);
      ctx.moveTo(p.x, y);
      ctx.lineTo(p.x + p.w, y);
    }
    ctx.stroke();

    ctx.strokeStyle = this._axisStylePaint(xAxis, "grid_color", this.theme.grid);
    ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(xAxis, "grid_width", 1));
    ctx.globalAlpha = this._axisStyleNumber(xAxis, "grid_opacity", 1);
    ctx.setLineDash(this._axisGridDash(xAxis));
    ctx.beginPath();
    for (const v of (hideX || polarGeom ? [] : xt.ticks)) {
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
    for (const v of (hideY || polarGeom ? [] : yt.ticks)) {
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

    // Axis baselines render in the labels overlay — *above* the marks canvas —
    // so a filled mark (bars, area) sits under a crisp, continuous baseline
    // instead of covering the chrome line drawn behind it (grid lines stay on
    // the chrome canvas, behind the data). Rebuilt with the labels; static
    // between throttled zoom frames since the plot rect doesn't move on zoom.
    const tickParts = (axis) => {
      const length = Math.max(0, this._axisStyleNumber(axis, "tick_length", 0));
      const width = Math.max(0.5, this._axisStyleNumber(axis, "tick_width", 1));
      const direction = String(this._axisStyleValue(axis, "tick_direction") || "out");
      if (direction === "in") return { inward: length, outward: 0, width };
      if (direction === "inout") return { inward: length / 2, outward: length / 2, width };
      return { inward: 0, outward: length, width };
    };
    if (updateLabels) {
      const rule = (
        styleAxis,
        left,
        top,
        w,
        h,
        colorKey = "axis_color",
        slot = "axis_line",
        tickKind = "",
        side = "",
      ) => {
        const d = document.createElement("div");
        d.style.cssText =
          `position:absolute;left:${left}px;top:${top}px;` +
          "pointer-events:none;";
        d.style.setProperty("--xy-axis-rule-width", `${w}px`);
        d.style.setProperty("--xy-axis-rule-height", `${h}px`);
        d.style.setProperty(
          "--xy-axis-rule-paint",
          this._axisStylePaint(styleAxis, colorKey, this.theme.axis),
        );
        d.dataset.xyAxis = styleAxis && styleAxis.id !== undefined
          ? String(styleAxis.id)
          : "";
        d.dataset.xyAxisSide = side || this._axisDefaultSide(styleAxis);
        if (tickKind) d.dataset.xyTickKind = tickKind;
        this._applySlot(d, slot);
        this.labels.appendChild(d);
      };
      // Under polar the frame is one ring drawn on the chrome canvas below;
      // "side" has no polar meaning, so frame_sides is not consulted. Axis
      // spines are background-coloured DIVs and cannot express a circle.
      const frameSides = polarGeom
        ? []
        : (Array.isArray(s.frame_sides)
          ? s.frame_sides
          : [xAxis.side || "bottom", yAxis.side || "left"]);
      const explicitFrameSides = !polarGeom && Array.isArray(s.frame_sides);
      if (!hideY || explicitFrameSides) {
        const yWidth = Math.max(1, this._axisStyleNumber(yAxis, "axis_width", 1));
        if (frameSides.includes("left")) {
          rule(yAxis, p.x, p.y, yWidth, p.h, "axis_color", "axis_line", "", "left");
        }
        if (frameSides.includes("right")) {
          rule(
            yAxis,
            p.x + p.w - yWidth,
            p.y,
            yWidth,
            p.h,
            "axis_color",
            "axis_line",
            "",
            "right",
          );
        }
      }
      if (!hideX || explicitFrameSides) {
        const xHeight = Math.max(1, this._axisStyleNumber(xAxis, "axis_width", 1));
        if (frameSides.includes("top")) {
          rule(xAxis, p.x, p.y, p.w, xHeight, "axis_color", "axis_line", "", "top");
        }
        if (frameSides.includes("bottom")) {
          rule(
            xAxis,
            p.x,
            p.y + p.h - xHeight,
            p.w,
            xHeight,
            "axis_color",
            "axis_line",
            "",
            "bottom",
          );
        }
      }
      for (const axis of extraXAxes) {
        if (this._axisTickLabelStrategy(axis) === "none") continue;
        const h = Math.max(1, this._axisStyleNumber(axis, "axis_width", 1));
        const y = axis.side === "top" ? p.y : p.y + p.h - h;
        rule(axis, p.x, y, p.w, h, "axis_color", "axis_line", "", axis.side);
      }
      for (const axis of extraYAxes) {
        if (this._axisTickLabelStrategy(axis) === "none") continue;
        const w = Math.max(1, this._axisStyleNumber(axis, "axis_width", 1));
        const x = axis.side === "left" ? p.x : p.x + p.w - w;
        rule(axis, x, p.y, w, p.h, "axis_color", "axis_line", "", axis.side);
      }

      // Edge-anchored tick marks have no polar geometry; the spec records
      // tick_length/tick_width/tick_direction as ignored under polar.
      if (!hideX && !polarGeom) {
        const minorTick = tickParts(xmAxis);
        const minorSide = xAxis.side || "bottom";
        const minorEdge = minorSide === "top" ? p.y : p.y + p.h;
        for (const value of xmt) {
          const x = this._dataPx("x", value);
          if (!Number.isFinite(x) || x < p.x - 1 || x > p.x + p.w + 1) continue;
          const top = minorSide === "top"
            ? minorEdge - minorTick.outward : minorEdge - minorTick.inward;
          rule(
            xmAxis, x - minorTick.width / 2, top, minorTick.width,
            minorTick.inward + minorTick.outward, "tick_color",
            "tick_mark", "minor", minorSide,
          );
        }
        const tick = tickParts(xAxis);
        for (const side of this._axisTickSides(xAxis)) {
          const edge = side === "top" ? p.y : p.y + p.h;
          for (const value of xt.ticks) {
            const x = this._dataPx("x", value);
            if (!Number.isFinite(x) || x < p.x - 1 || x > p.x + p.w + 1) continue;
            const top = side === "top" ? edge - tick.outward : edge - tick.inward;
            rule(
              xAxis,
              x - tick.width / 2,
              top,
              tick.width,
              tick.inward + tick.outward,
              "tick_color",
              "tick_mark",
              "major",
              side,
            );
          }
        }
      }
      if (!hideY && !polarGeom) {
        const minorTick = tickParts(ymAxis);
        const minorSide = yAxis.side || "left";
        const minorEdge = minorSide === "right" ? p.x + p.w : p.x;
        for (const value of ymt) {
          const y = this._dataPx("y", value);
          if (!Number.isFinite(y) || y < p.y - 1 || y > p.y + p.h + 1) continue;
          const left = minorSide === "right"
            ? minorEdge - minorTick.inward : minorEdge - minorTick.outward;
          rule(
            ymAxis, left, y - minorTick.width / 2,
            minorTick.inward + minorTick.outward, minorTick.width, "tick_color",
            "tick_mark", "minor", minorSide,
          );
        }
        const tick = tickParts(yAxis);
        for (const side of this._axisTickSides(yAxis)) {
          const edge = side === "right" ? p.x + p.w : p.x;
          for (const value of yt.ticks) {
            const y = this._dataPx("y", value);
            if (!Number.isFinite(y) || y < p.y - 1 || y > p.y + p.h + 1) continue;
            const left = side === "right" ? edge - tick.inward : edge - tick.outward;
            rule(
              yAxis,
              left,
              y - tick.width / 2,
              tick.inward + tick.outward,
              tick.width,
              "tick_color",
              "tick_mark",
              "major",
              side,
            );
          }
        }
      }
      for (const axis of extraXAxes) {
        if (this._axisTickLabelStrategy(axis) === "none") continue;
        const ticks = this._axisTicks(
          axis.id,
          this._axisTickTarget(axis.id, Math.max(3, p.w / (axis.kind === "time" ? 90 : 80))),
        );
        const tick = tickParts(axis);
        for (const side of this._axisTickSides(axis)) {
          const edge = side === "top" ? p.y : p.y + p.h;
          for (const value of ticks.ticks) {
            const x = this._dataPx(axis.id, value);
            if (!Number.isFinite(x) || x < p.x - 1 || x > p.x + p.w + 1) continue;
            const top = side === "top" ? edge - tick.outward : edge - tick.inward;
            rule(
              axis,
              x - tick.width / 2,
              top,
              tick.width,
              tick.inward + tick.outward,
              "tick_color",
              "tick_mark",
              "major",
              side,
            );
          }
        }
      }
      for (const axis of extraYAxes) {
        if (this._axisTickLabelStrategy(axis) === "none") continue;
        const ticks = this._axisTicks(
          axis.id,
          this._axisTickTarget(axis.id, Math.max(3, p.h / 45)),
        );
        const tick = tickParts(axis);
        for (const side of this._axisTickSides(axis)) {
          const edge = side === "right" ? p.x + p.w : p.x;
          for (const value of ticks.ticks) {
            const y = this._dataPx(axis.id, value);
            if (!Number.isFinite(y) || y < p.y - 1 || y > p.y + p.h + 1) continue;
            const left = side === "right" ? edge - tick.inward : edge - tick.outward;
            rule(
              axis,
              left,
              y - tick.width / 2,
              tick.inward + tick.outward,
              tick.width,
              "tick_color",
              "tick_mark",
              "major",
              side,
            );
          }
        }
      }
    }

    const label = (text, css, axis, kind = "tick", extraStyle = null, yPlacement = null) => {
      if (!updateLabels) return null;
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
      d.style.cssText =
        `position:absolute;line-height:1.2;white-space:pre-line;text-align:center;` +
        `${color}${size}${css}`;
      // Categorical y labels can exceed the space between their pinned anchor
      // and the chart edge. Placement owns side/anchor/angle; consume that
      // metadata here instead of re-deriving it and drifting from rendering.
      if (kind === "tick" && axis && axis.kind === "category" && yPlacement) {
        d.title = text;
        d.setAttribute("aria-label", text);
        d.style.overflow = "hidden";
        d.style.textOverflow = "ellipsis";
        d.style.boxSizing = "border-box";
      }
      this._applySlot(d, kind === "label" ? "axis_title" : "tick_label");
      const axisLabelStyle = kind === "label" ? {
        "font-family": this._axisStyleValue(axis, "label_font_family"),
        "font-style": this._axisStyleValue(axis, "label_font_style"),
        "font-weight": this._axisStyleValue(axis, "label_font_weight"),
      } : null;
      if (axisLabelStyle) {
        for (const key of Object.keys(axisLabelStyle)) {
          if (axisLabelStyle[key] === undefined) delete axisLabelStyle[key];
        }
      }
      this._applyStyle(
        d,
        axisLabelStyle || extraStyle
          ? { ...(axisLabelStyle || {}), ...(extraStyle || {}) }
          : null,
      );
      this.labels.appendChild(d);
      if (kind === "tick" && axis && axis.kind === "category" && yPlacement) {
        // Rotation contributes half the untransformed label height to each
        // horizontal side. The width contribution depends on both the anchor
        // and cos(angle); solve the two edge inequalities analytically so no
        // post-layout search/reflow loop is needed.
        const height = d.offsetHeight;
        const radians = Number(yPlacement.angle || 0) * Math.PI / 180;
        const cosine = Math.cos(radians);
        const heightExtent = Math.abs(Math.sin(radians)) * height / 2;
        const fractions = yPlacement.anchor === "start"
          ? [0, 1] : yPlacement.anchor === "end" ? [-1, 0] : [-0.5, 0.5];
        const projected = fractions.map((fraction) => fraction * cosine);
        const leftCoefficient = Math.max(0, -Math.min(...projected));
        const rightCoefficient = Math.max(0, Math.max(...projected));
        const edge = 4;
        const leftBudget = yPlacement.pin - edge - heightExtent;
        const rightBudget = this.size.w - edge - yPlacement.pin - heightExtent;
        const caps = [];
        if (leftCoefficient > 1e-6) caps.push(leftBudget / leftCoefficient);
        if (rightCoefficient > 1e-6) caps.push(rightBudget / rightCoefficient);
        const available = Math.max(1, Math.min(...(caps.length ? caps : [this.size.w])));
        d.style.maxWidth =
          `min(var(--chart-tick-label-max-width, ${available}px), ${available}px)`;
      }
      return d;
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
    // Spine→label distance. mpl measures tick padding from the outward end of
    // the tick mark, and a `top` label then needs `fontRoomPx` more to clear its
    // own line box. That derived geometry only applies once the axis authors
    // tick geometry: core's default tick_length is 0 and it has no default
    // tick_label_pad, so deriving it unconditionally would move the labels of
    // every chart that styles no ticks. Unstyled axes keep `unstyled`, the
    // per-side gap this client has always used (pyplot supplies mpl's
    // {x,y}tick.major.pad, so it takes the derived branch). Mirrors
    // `_axis_tick_label_offset` in `_svg.py`/`_raster.py`.
    const tickLabelOffset = (axis, unstyled, fontRoomPx = 0) => {
      const rawPadding = this._axisStyleValue(axis, "tick_padding");
      const rawLength = this._axisStyleValue(axis, "tick_length");
      const rawWidth = this._axisStyleValue(axis, "tick_width");
      const hiddenSentinel = Number(rawLength) === 0 && Number(rawWidth) === 0;
      const authored = rawPadding !== undefined
        || (rawLength !== undefined && !hiddenSentinel);
      if (!authored) return unstyled;
      const length = Math.max(0, this._axisStyleNumber(axis, "tick_length", 0));
      const direction = String(this._axisStyleValue(axis, "tick_direction") || "out");
      const outward = direction === "in" ? 0 : direction === "inout" ? length / 2 : length;
      const pad = outward + this._axisStyleNumber(axis, "tick_padding", 4);
      return pad + fontRoomPx;
    };
    for (const side of this._axisTickLabelSides(xAxis)) {
      // Polar places its own labels around the rim below; sides are meaningless
      // on a disc. Guarded here rather than around the loop so all four axis
      // paths keep calling _axisTickLabelSides (asserted by a source guard in
      // tests/pyplot/test_tick_side_rendering.py).
      if (polarGeom) break;
      const sideAxis = { ...xAxis, side };
      for (const item of this._layoutTickLabels(sideAxis, "x", xLabelCandidates)) {
        const rowOffset = Number(item.row || 0) * (Math.max(8, tickLabelSize) + 4);
        const top = side === "top"
          ? p.y - tickLabelOffset(xAxis, 18, Math.max(8, tickLabelSize) * 1.2) - rowOffset
          : p.y + p.h + tickLabelOffset(xAxis, 6) + rowOffset;
        const placement = this._xTickLabelTransform(sideAxis, item.angle);
        label(
          item.text,
          `left:${item.pos}px;top:${top}px;transform:${placement.transform};` +
            `transform-origin:${placement.origin};`,
          sideAxis,
        );
      }
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
      for (const side of this._axisTickLabelSides(axis)) {
        const sideAxis = { ...axis, side };
        for (const item of this._layoutTickLabels(sideAxis, "x", labelCandidates)) {
          const tickLabelSize = this._axisStyleNumber(
            axis,
            "tick_label_size",
            this._axisStyleNumber(axis, "tick_size", 11),
          );
          const rowOffset = Number(item.row || 0) * (Math.max(8, tickLabelSize) + 4);
          const top = side === "top"
            ? p.y - tickLabelOffset(axis, 18, Math.max(8, tickLabelSize) * 1.2) - rowOffset
            : p.y + p.h + tickLabelOffset(axis, 6) + rowOffset;
          const placement = this._xTickLabelTransform(sideAxis, item.angle);
          label(
            item.text,
            `left:${item.pos}px;top:${top}px;transform:${placement.transform};` +
              `transform-origin:${placement.origin};`,
            sideAxis,
          );
        }
      }
      if (axis.label && this._axisTickLabelStrategy(axis) !== "none") {
        const top = axis.side === "top" ? p.y - 34 : p.y + p.h + 24;
        const fallbackCss =
          `left:${p.x + p.w / 2}px;top:${top}px;transform:translateX(-50%);`;
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
    const yLabelPlacement = (axis, onRight, item) => {
      const offset = tickLabelOffset(axis, 8);
      const pin = onRight ? p.x + p.w + offset : p.x - offset;
      const anchor = this._axisTickLabelAnchor(axis) ?? (onRight ? "start" : "end");
      const angle = Number(item.angle || 0);
      const shift = anchor === "end" ? "-100%" : anchor === "start" ? "0%" : "-50%";
      const originX = anchor === "end" ? "right" : anchor === "start" ? "left" : "center";
      return {
        css: `left:${pin}px;top:${item.pos}px;` +
          `transform:translate(${shift},-50%) rotate(${angle}deg);` +
          `transform-origin:${originX} center;`,
        pin,
        anchor,
        angle,
      };
    };
    if (polarGeom) {
      // Angular labels around the rim, radial labels along the 22.5-degree
      // spoke. Mirrors _polar_tick_labels in python/xy/_svg.py; the cartesian
      // label machinery is edge-relative and neither concept survives a disc.
      const RLABEL = (POLAR_RLABEL_DEG * Math.PI) / 180;
      const GAP = POLAR_TICK_GAP;
      // "off" hides only the label text; "none" (hideX/hideY) kills the chrome.
      const offX = this._axisTickLabelStrategy(xAxis) === "off";
      const offY = this._axisTickLabelStrategy(yAxis) === "off";
      if (!hideX && !offX) {
        for (const v of (xt.labels || xt.ticks)) {
          const a = this._polarThetaAngle(polarGeom, v);
          const cos = Math.cos(a);
          const sin = Math.sin(a);
          const lx = polarGeom.cx + (polarGeom.radius + GAP) * cos;
          const ly = polarGeom.cy - (polarGeom.radius + GAP) * sin;
          const align = Math.abs(cos) < 0.3 ? "-50%" : (cos > 0 ? "0%" : "-100%");
          const vshift = Math.abs(sin) < 0.3 ? "-50%" : (sin > 0 ? "-100%" : "0%");
          const spinX = Number(xAxis.tick_label_angle) || 0;
          label(
            this._axisTickText(xAxis, v, xt.step),
            `left:${lx}px;top:${ly}px;transform:translate(${align}, ${vshift})` +
              (spinX ? ` rotate(${spinX}deg)` : "") + ";",
            xAxis,
          );
        }
      }
      if (!hideY && !offY) {
        const sectorSweep = Math.abs(polarGeom.dirUnit)
          * Math.max(0, polarGeom.thetaEnd - polarGeom.thetaStart);
        const labelOffset = Math.min(RLABEL, sectorSweep / 2);
        const angle = this._polarThetaAngle(polarGeom, polarGeom.thetaStart)
          + Math.sign(polarGeom.dirUnit || 1) * labelOffset;
        for (const v of this._polarThinRadialLabels(yt.labels || yt.ticks, polarGeom)) {
          const radius = this._polarRadius(polarGeom, v);
          if (!(radius > 0) || radius > polarGeom.radius + 1e-6) continue;
          const spinY = Number(yAxis.tick_label_angle) || 0;
          label(
            this._axisTickText(yAxis, v, yt.step),
            `left:${polarGeom.cx + radius * Math.cos(angle) + 3}px;` +
              `top:${polarGeom.cy - radius * Math.sin(angle) - 3}px;` +
              `transform:translate(0, -100%)` + (spinY ? ` rotate(${spinY}deg)` : "") + ";",
            yAxis,
          );
        }
      }
    }
    for (const side of this._axisTickLabelSides(yAxis)) {
      if (polarGeom) break;
      const sideAxis = { ...yAxis, side };
      for (const item of this._layoutTickLabels(sideAxis, "y", yLabelCandidates)) {
        const placement = yLabelPlacement(sideAxis, side === "right", item);
        label(item.text, placement.css, sideAxis, "tick", null, placement);
      }
    }
    const pendingYTitleAttachments = [];
    const measureYTitleAttachment = (title, axis, onRight, root) => {
      if (!title || !axis) return;
      const position = String(axis.label_position || "center").replace(/-/g, "_");
      if (position.startsWith("inside_")) return;
      const tickLabels = [...this.labels.children].filter((element) =>
        element.dataset.xyLabelKind === "tick"
        && element.dataset.xyAxis === String(axis.id ?? "")
        && element.dataset.xyAxisSide === (onRight ? "right" : "left")
      );
      const tickRects = tickLabels.map((element) => element.getBoundingClientRect());
      const titleRect = title.getBoundingClientRect();
      const fontSize = parseFloat(getComputedStyle(title).fontSize) || 12;
      const rawOffset = axis.label_offset;
      const gap = rawOffset !== undefined
        && rawOffset !== null
        && Number.isFinite(Number(rawOffset))
        ? Number(rawOffset)
        : 0.4 * fontSize;
      // Matplotlib centers the title along the axis, then offsets it
      // perpendicular to the union of the tick-label bounds and the
      // corresponding spine. Including the spine keeps inward/negative-pad
      // labels from pulling an outside title back into the plot.
      const spineEdge = root.left + (onRight ? p.x + p.w : p.x);
      const tickEdge = onRight
        ? Math.max(spineEdge, ...tickRects.map((rect) => rect.right))
        : Math.min(spineEdge, ...tickRects.map((rect) => rect.left));
      const targetEdge = onRight ? tickEdge + gap : tickEdge - gap;
      const currentEdge = onRight ? titleRect.left : titleRect.right;
      const currentLeft = parseFloat(title.style.left) || 0;
      const delta = targetEdge - currentEdge;
      // Keep an unusually large title inside the chart canvas. Moving an
      // absolutely positioned label by `delta` translates its measured box by
      // the same amount, so derive the clamp from the captured geometry and
      // avoid a write-then-layout-read on every chrome redraw.
      const adjustedLeft = titleRect.left + delta;
      const adjustedRight = titleRect.right + delta;
      const correction = adjustedLeft < root.left
        ? root.left - adjustedLeft + 1
        : adjustedRight > root.right ? root.right - adjustedRight - 1 : 0;
      return { title, left: currentLeft + delta + correction };
    };
    const renderYTitle = (axis, text, onRight) => {
      const angle = onRight ? 90 : -90;
      const fallbackCss =
        `left:${onRight ? p.x + p.w : p.x}px;top:${p.y + p.h / 2}px;` +
        `transform:translate(-50%,-50%) rotate(${angle}deg);` +
        "transform-origin:center;";
      const placement = this._axisLabelCss(axis, "y", fallbackCss);
      const title = label(text, placement.css, axis, "label", placement.style);
      // A structured CSS label_position is the placement authority. It may
      // deliberately omit `left` in favor of `right`, so tick attachment must
      // not synthesize a competing left offset.
      if (title && placement.style === null) {
        pendingYTitleAttachments.push({ title, axis, onRight });
      }
    };
    for (const axis of extraYAxes) {
      const ticks = this._axisTicks(axis.id, this._axisTickTarget(axis.id, Math.max(3, p.h / 45)));
      const labelCandidates = [];
      for (const v of (ticks.labels || ticks.ticks)) {
        const py = this._dataPx(axis.id, v);
        if (py < p.y - 1 || py > p.y + p.h + 1) continue;
        const text = this._axisTickText(axis, v, ticks.step);
        labelCandidates.push({ pos: py, text });
      }
      for (const side of this._axisTickLabelSides(axis)) {
        const sideAxis = { ...axis, side };
        for (const item of this._layoutTickLabels(sideAxis, "y", labelCandidates)) {
          const placement = yLabelPlacement(sideAxis, side === "right", item);
          label(item.text, placement.css, sideAxis, "tick", null, placement);
        }
      }
      if (axis.label && this._axisTickLabelStrategy(axis) !== "none") {
        renderYTitle(axis, axis.label, axis.side !== "left");
      }
    }
    if (s.x_axis.label && !hideX) {
      const top = xAxis.side === "top" ? p.y - 34 : p.y + p.h + 24;
      const fallbackCss = `left:${p.x + p.w / 2}px;top:${top}px;transform:translateX(-50%);`;
      const placement = this._axisLabelCss(xAxis, "x", fallbackCss);
      label(s.x_axis.label, placement.css, xAxis, "label", placement.style);
    }
    if (s.y_axis.label && !hideY) {
      renderYTitle(yAxis, s.y_axis.label, yAxis.side === "right");
    }
    if (pendingYTitleAttachments.length) {
      // Finish creating every y-axis label before the first geometry read,
      // then apply all offsets after the complete measurement pass. Keeping
      // DOM reads and writes in separate phases avoids one forced layout per
      // named axis during settled interaction redraws.
      const root = this.root.getBoundingClientRect();
      const adjustments = pendingYTitleAttachments
        .map(({ title, axis, onRight }) =>
          measureYTitleAttachment(title, axis, onRight, root))
        .filter(Boolean);
      for (const { title, left } of adjustments) {
        title.style.left = `${left}px`;
      }
    }
    this._drawAnnotationLabels(updateLabels);
    // Label layout resolves responsive callout offsets before the pointer is
    // painted, keeping its start attached when an edge clamp moves the text.
    this._drawAuthoredScatterMarkers(octx);
    this._drawAnnotationShapes(octx);
  }

  _interactionTransitionActive() {
    // Data transitions stay pickable: the pick shader follows the same
    // interpolated positions as the visible point shader. View and LOD
    // handoffs still suppress hit-testing while their mapping changes.
    const activeStart = (v) => v !== undefined && v !== null;
    return !!this._viewAnim || this.gpuTraces.some((g) =>
      activeStart(g._densityFadeStart) ||
      activeStart(g._densitySwitchFadeStart) ||
      activeStart(g._drillFadeStart) ||
      activeStart(g._drillExitFadeStart) ||
      !!g._densityNormAnim);
  }

  // -- picking (§17) --------------------------------------------------------

  _renderPickPass() {
    const gl = this.gl;
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
      // Legend-hidden traces draw nothing, so they must pick nothing.
      const pg = g._legendHidden ? null : g.tier === "density"
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
      // The pick buffer must use the SAME transform as the colour pass. Left
      // cartesian under polar it still returns ids, so the picture stays right
      // while hover silently reports whichever row happens to sit at the
      // untransformed location.
      this._setPolarUniforms(prog);
      const zoomStyle = this._pointZoomStyle(pg);
      gl.uniform1f(u("u_size"), pg.size * zoomStyle.sizeFactor);
      gl.uniform1i(u("u_sizeMode"), pg.sizeMode);
      gl.uniform2f(u("u_sizeRange"), pg.sizeRange[0] * zoomStyle.sizeFactor,
        pg.sizeRange[1] * zoomStyle.sizeFactor);
      const transitionOn = !!(pg._transitionPrevXBuf && pg._transitionPrevYBuf);
      gl.uniform1i(u("u_transitionActive"), transitionOn ? 1 : 0);
      gl.uniform1f(u("u_transitionProgress"), pg._transitionPositionProgress ?? 1);
      gl.uniform1i(u("u_pick_base"), base);
      g.pickBase = base;
      g.pickCount = pg.n;
      const sizeOn = pg.sizeMode === 1 && pg.sBuf;
      this._bindVao(
        pg,
        "pick",
        [pg.xBuf._fcId, pg.yBuf._fcId, sizeOn ? pg.sBuf._fcId : 0,
          transitionOn ? pg._transitionPrevXBuf._fcId : 0,
          transitionOn ? pg._transitionPrevYBuf._fcId : 0],
        () => {
          this._vaoAttr(ATTR_SLOTS.ax, pg.xBuf, 0, 0);
          this._vaoAttr(ATTR_SLOTS.ay, pg.yBuf, 0, 0);
          if (sizeOn) this._vaoAttr(ATTR_SLOTS.a_sval, pg.sBuf, 0, 0);
          if (transitionOn) {
            this._vaoAttr(ATTR_SLOTS.a_prevx, pg._transitionPrevXBuf, 0, 0);
            this._vaoAttr(ATTR_SLOTS.a_prevy, pg._transitionPrevYBuf, 0, 0);
          }
        }
      );
      if (!sizeOn) gl.vertexAttrib1f(ATTR_SLOTS.a_sval, 0.5);
      gl.drawArrays(gl.POINTS, 0, pg.n);
      base += pg.n;
    }
    gl.enable(gl.BLEND);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this._pickDirty = false;
    return true;
  }

  _renderPick() {
    if (this._pickW !== this.canvas.width || this._pickH !== this.canvas.height) {
      this._allocPickTex(); // deferred resize catch-up
    }
    if (this._glHost) {
      return this._glHost.pick(
        this,
        this.pickFbo,
        this.canvas.width,
        this.canvas.height,
        () => this._renderPickPass(),
      ) === true;
    }
    return this._renderPickPass();
  }

  _pickAt(cssX, cssY) {
    if (
      !this._pickable ||
      this._glLost ||
      !this.gl ||
      this.gl.isContextLost()
    ) return null;
    if (this._pickDirty) {
      try {
        if (!this._renderPick()) return null;
      } catch (err) {
        // Native eviction can race pointer movement before the asynchronous
        // webglcontextlost event updates `_glLost`. Suppress only that lost-
        // context case; real shader/program defects must remain observable.
        if (!this.gl || this.gl.isContextLost()) return null;
        throw err;
      }
    }
    const gl = this.gl;
    const px = Math.round(cssX * this.dpr);
    const py = Math.round((this.plot.h - cssY) * this.dpr); // GL origin bottom-left
    if (px < 0 || py < 0 || px >= this.canvas.width || py >= this.canvas.height) return null;
    const buf = new Uint8Array(4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.pickFbo);
    if (this._glHost) gl.readBuffer(gl.COLOR_ATTACHMENT0);
    gl.readPixels(px, py, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, buf);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    // Reassemble the global 32-bit id; zero is the background sentinel.
    const id = buf[0] + buf[1] * 0x100 + buf[2] * 0x10000 + buf[3] * 0x1000000;
    if (id === 0) return null;
    const g = this.gpuTraces.find(
      (t) => t.pickBase > 0 && id >= t.pickBase && id < t.pickBase + t.pickCount
    );
    if (!g) return null;
    const raw = id - g.pickBase;
    // Category-filtered buffers draw a subset (interaction spec §10):
    // `index` translates back to the shipped row so CPU readouts and kernel
    // picks stay exact; `drawIndex` keeps addressing the filtered GPU
    // buffers (hover marker).
    const index = g._visMap ? g._visMap[raw] : raw;
    return { trace: g.trace.id, index, drawIndex: raw, g };
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
    const geom = this._polarGeometry();
    if (geom) {
      // Screen -> (theta, r), the inverse of xyPolarPos. cssX/cssY are canvas
      // relative, whereas geometry is chart-relative.
      const dx = cssX - (geom.cx - this.plot.x);
      const dy = (geom.cy - this.plot.y) - cssY; // flip out of screen space
      const displayed = Math.hypot(dx, dy) / (geom.radius || 1);
      if (displayed > 1 + 1e-10 || displayed < geom.hole - 1e-10) {
        return [NaN, NaN];
      }
      const theta = this._polarThetaValue(geom, Math.atan2(dy, dx));
      if (!this._polarThetaVisible(geom, theta)) return [NaN, NaN];
      const radialFraction = (displayed - geom.hole) / Math.max(1 - geom.hole, 1e-30);
      const rCoord = geom.rOrigin + radialFraction * (geom.rHi - geom.rOrigin);
      const rMin = Math.min(geom.rLo, geom.rHi);
      const rMax = Math.max(geom.rLo, geom.rHi);
      if (rCoord < rMin - 1e-10 || rCoord > rMax + 1e-10) return [NaN, NaN];
      return [theta, this._axisValue(yAxis, rCoord)];
    }
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
      const starts = g._transitionPrevXValues;
      const progress = g._transitionPositionProgress;
      const xEncoded = starts && Number.isFinite(progress)
        ? starts[i] + (cpu.x[i] - starts[i]) * progress
        : cpu.x[i];
      const x = xEncoded / (xMeta.scale || 1) + xMeta.offset;
      const d = Math.abs(this._axisCoord(axis, x) - target);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    }
    return best;
  }

  _nearestPolarCpuIndex(g, cssX, cssY) {
    const cpu = g && g._cpu;
    if (!cpu || !cpu.x || !cpu.y) return -1;
    const xMeta = cpu.xMeta || g.xMeta;
    const yMeta = cpu.yMeta || g.yMeta;
    const progress = g._transitionPositionProgress;
    const limit = Math.min(cpu.x.length, cpu.y.length, g.n || cpu.x.length);
    const geom = this._polarGeometry();
    let best = -1;
    let bestDist = Infinity;
    for (let i = 0; i < limit; i++) {
      const xEncoded = g._transitionPrevXValues && Number.isFinite(progress)
        ? g._transitionPrevXValues[i] + (cpu.x[i] - g._transitionPrevXValues[i]) * progress
        : cpu.x[i];
      const yEncoded = g._transitionPrevYValues && Number.isFinite(progress)
        ? g._transitionPrevYValues[i] + (cpu.y[i] - g._transitionPrevYValues[i]) * progress
        : cpu.y[i];
      const x = xEncoded / (xMeta.scale || 1) + xMeta.offset;
      const y = yEncoded / (yMeta.scale || 1) + yMeta.offset;
      const [chartX, chartY] = this._projectDataPoint(g.xAxis, g.yAxis, x, y, geom);
      const dist = Math.hypot(chartX - this.plot.x - cssX, chartY - this.plot.y - cssY);
      if (Number.isFinite(dist) && dist < bestDist) {
        bestDist = dist;
        best = i;
      }
    }
    return best;
  }

  _segmentHover(g, cssX, cssY, maxPx) {
    const cpu = g && g._segmentCpu;
    if (!cpu) return null;
    let best = null;
    const limit = Math.min(cpu.x0.length, cpu.x1.length, cpu.y0.length, cpu.y1.length, g.n);
    const geom = this._polarGeometry();
    for (let i = 0; i < limit; i++) {
      const [[x0, y0], [x1, y1]] = this._projectSegmentEndpoints(g, cpu, i, geom);
      const ax = x0 - this.plot.x;
      const ay = y0 - this.plot.y;
      const bx = x1 - this.plot.x;
      const by = y1 - this.plot.y;
      if (![ax, ay, bx, by].every(Number.isFinite)) continue;
      const vx = bx - ax;
      const vy = by - ay;
      const denom = vx * vx + vy * vy;
      const t = denom > 0
        ? Math.max(0, Math.min(1, ((cssX - ax) * vx + (cssY - ay) * vy) / denom))
        : 0;
      const dist = Math.hypot(cssX - (ax + t * vx), cssY - (ay + t * vy));
      if (dist <= maxPx && (!best || dist < best.dist)) {
        best = { trace: g.trace.id, index: i, g, dist, synthetic: true };
      }
    }
    return best;
  }

  _hoverAt(cssX, cssY) {
    const maxPx = 12;
    let best = null;
    const polarGeom = this._polarGeometry();
    for (const g of this.gpuTraces) {
      if (g.tier === "density") continue;
      // A legend-hidden series draws nothing, so it must not answer hover
      // either (interaction spec §10) — before this guard every CPU-hover
      // kind (bar, rect, ribbon, funnel) kept reporting invisible geometry.
      if (g._legendHidden) continue;
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
      if (g._cpuRibbon) {
        const hit = this._ribbonHover(g, dataX, dataY);
        if (hit) return hit;
        continue;
      }
      if (g._cpuFunnel) {
        // Before the generic point path: the funnel's _cpu holds stage
        // centers for keyboard traversal, not hoverable point geometry.
        const hit = this._funnelHover(g, dataX, dataY);
        if (hit) return hit;
        continue;
      }
      if (g._cpuRect) {
        const hit = this._rectHover(g, dataX, dataY);
        if (hit) return hit;
        continue;
      }
      if (g._segmentCpu) {
        const hit = this._segmentHover(g, cssX, cssY, maxPx);
        if (hit && (!best || hit.dist < best.dist)) best = hit;
        continue;
      }
      if (!g._cpu || !g._cpu.x || !g._cpu.y) continue;
      const idx = polarGeom
        ? this._nearestPolarCpuIndex(g, cssX, cssY)
        : this._nearestCpuIndex(g, dataX);
      if (idx < 0) continue;
      const progress = g._transitionPositionProgress;
      const xEncoded = g._transitionPrevXValues && Number.isFinite(progress)
        ? g._transitionPrevXValues[idx] + (g._cpu.x[idx] - g._transitionPrevXValues[idx]) * progress
        : g._cpu.x[idx];
      const yEncoded = g._transitionPrevYValues && Number.isFinite(progress)
        ? g._transitionPrevYValues[idx] + (g._cpu.y[idx] - g._transitionPrevYValues[idx]) * progress
        : g._cpu.y[idx];
      const x = xEncoded / (g._cpu.xMeta.scale || 1) + g._cpu.xMeta.offset;
      const y = yEncoded / (g._cpu.yMeta.scale || 1) + g._cpu.yMeta.offset;
      const [chartX, chartY] = this._projectDataPoint(
        g.xAxis,
        g.yAxis,
        x,
        y,
        polarGeom,
      );
      const px = chartX - this.plot.x;
      const py = chartY - this.plot.y;
      const dist = Math.hypot(px - cssX, py - cssY);
      if (dist <= maxPx && (!best || dist < best.dist)) {
        best = { trace: g.trace.id, index: idx, g, dist, synthetic: true };
      }
    }
    return best;
  }

  // Seam-aware angular containment for wedge hover: |dataX - centre| in
  // unwrapped data space misses any wedge straddling theta = 0/turn (a
  // wind-rose "N" sector), which draws fine and was silently un-hoverable on
  // its wrap side. Distances re-base through the same positive-mod the
  // heatmap inverse uses (spec section 3.2: any angular metric must wrap).
  _polarAngularDistance(geom, a, b) {
    const turn = geom.turn || 1;
    const forward = this._polarPositiveMod(a - b, turn);
    return Math.min(forward, turn - forward);
  }

  _barHover(g, dataX, dataY) {
    const cpu = g._cpu;
    const horizontal = g.orientation === 1;
    const geom = this._polarGeometry();
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
      } else {
        const near = geom
          ? this._polarAngularDistance(geom, dataX, x) <= g.width / 2
          : Math.abs(dataX - x) <= g.width / 2;
        if (near && dataY >= lo && dataY <= hi) {
          return { trace: g.trace.id, index: i, g, synthetic: true };
        }
      }
    }
    return null;
  }

  _rectHover(g, dataX, dataY) {
    const r = g._cpuRect;
    const geom = this._polarGeometry();
    const limit = Math.min(r.x0.length, r.x1.length, r.y0.length, r.y1.length, g.n || r.x0.length);
    for (let i = 0; i < limit; i++) {
      const x0 = this._decodeValue(r.x0, r.x0Meta, i);
      const x1 = this._decodeValue(r.x1, r.x1Meta, i);
      const y0 = this._decodeValue(r.y0, r.y0Meta, i);
      const y1 = this._decodeValue(r.y1, r.y1Meta, i);
      let insideX;
      if (geom) {
        // Both renderers draw the band as the DIRECT interval between the two
        // edges — GLSL takes `abs(a1 - a0)` with `dir = a1 >= a0 ? 1 : -1`, and
        // `wedge_angles` takes `min(raw0, raw1) .. max(raw0, raw1)` — so the
        // span is unwrapped and edge order carries no meaning. Measuring it
        // with a *directional* `mod(x1 - x0, turn)` while anchoring at
        // `min(x0, x1)` made the two disagree: a descending pair (350, 300)
        // covered 300..610 instead of 300..350. Only the offset needs wrapping,
        // so a seam-crossing bar whose edges are emitted unwrapped (-15..15) is
        // still reachable from dataX = 355.
        const turn = geom.turn || 1;
        const span = Math.abs(x1 - x0);
        insideX = this._polarPositiveMod(dataX - Math.min(x0, x1), turn) <= span;
      } else {
        insideX = dataX >= Math.min(x0, x1) && dataX <= Math.max(x0, x1);
      }
      if (insideX && dataY >= Math.min(y0, y1) && dataY <= Math.max(y0, y1)) {
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
    const geom = this._polarGeometry();
    const sampleX = geom
      ? x0 + this._polarPositiveMod(dataX - x0, geom.turn)
      : dataX;
    if (sampleX < Math.min(x0, x1) || sampleX > Math.max(x0, x1)
        || dataY < Math.min(y0, y1) || dataY > Math.max(y0, y1)) return null;
    // Mirror _drawHeatmap's display-orientation anchoring: on a reversed axis
    // buffer row/column 0 sits at the opposite end of the data range.
    const [ax0, ax1] = this._axisRange(g.xAxis) ?? [this.view.x0, this.view.x1];
    const [ay0, ay1] = this._axisRange(g.yAxis) ?? [this.view.y0, this.view.y1];
    const fx = ((ax0 ?? this.view.x0) > (ax1 ?? this.view.x1))
      ? (x1 - sampleX) : (sampleX - x0);
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
    if (this._interactionTransitionActive()) {
      const hadHover = this._hoverId !== -1;
      this._hoverId = -1;
      this._hoverTarget = null;
      this._lastHoverXY = null;
      this._pickSeq = (this._pickSeq || 0) + 1;
      this._hideTooltip();
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
      this._hideTooltip();
      if (hadHover) this._drawKeepPick();
      return;
    }
    const id = hit.trace * 1e9 + hit.index;
    this._lastHoverXY = { clientX: e.clientX, clientY: e.clientY };
    if (id === this._hoverId) {
      // Point tooltips stay attached to their data point. Sankey ribbons and
      // nodes — and funnel segments — cover an area instead, so keep their
      // tooltip at the pointer as it travels through the same picked shape.
      if (hit.g && (hit.g._cpuRibbon || hit.g._cpuFunnel)) {
        this._setTooltipAnchor(hit, this._lastRow, e.clientX, e.clientY);
        this._repositionTooltip();
      } else if (!this._tooltipAnchor) {
        this._renderTooltip(this._lastRow, e.clientX, e.clientY);
      }
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
    if (this._dataAnim) {
      this._emitAnimationLifecycle?.("end", this._dataAnim.phase, { cancelled: true });
    }
    if (this._governorRegistered) {
      XY_CONTEXT_GOVERNOR.unregister(this);
      this._governorRegistered = false;
    }
    this._ctxIo?.disconnect();
    this._ctxIo = null;
    clearTimeout(this._ctxRecoveryTimer);
    this._ctxRecoveryTimer = null;
    clearTimeout(this._glHostRecoveryTimer);
    this._glHostRecoveryTimer = null;
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
    clearTimeout(this._wheelZoomEndTimer);
    this._wheelZoomEndTimer = null;
    this._wheelGesture = null;
    this._linkChannel?.close?.();
    this._linkChannel = null;
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
    if (this._resizeRaf) cancelAnimationFrame(this._resizeRaf);
    this._resizeRaf = null;
    this._pendingResize = null;
    this._resizeNeedsMeasure = false;
    this._cancelViewAnimation();
    if (this._dataAnimRaf) cancelAnimationFrame(this._dataAnimRaf);
    this._dataAnimRaf = null;
    this._dataAnim = null;
    this._destroyTransitionOldTraces?.();
    this._destroyGlResources();
    // Release the GL context now instead of waiting for GC. Republishing a
    // figure destroys and rebuilds its view, and browsers cap live contexts
    // (~16); without an explicit loss the destroyed contexts pile up under
    // repeated rebuilds (e.g. an on_view_change-driven refresh) and trip the
    // "too many active WebGL contexts" eviction. Listeners are already removed
    // above and _destroyed is set, so the resulting event starts no recovery.
    if (this._glHost) {
      const host = this._glHost;
      this._glHost = null;
      host.release(this);
    } else {
      const loseExt = this.gl && this.gl.getExtension("WEBGL_lose_context");
      if (loseExt) loseExt.loseContext();
    }
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
    lodDropPointCache(this, g); // retired point windows die with the trace (T13)
    this._deleteVaos(g);
    this._deleteVaos(g._homeDecimated);
    this._deleteVaos(g.drill);
    // TRACE_GPU_BUFFERS is the single list of every buffer field a built trace
    // can own; the build paths and this teardown must not drift apart, so both
    // sides read the same names (see the constant for how it is enforced).
    this._deleteBuffers(g, TRACE_GPU_BUFFERS);
    // Only geometry is owned independently by the retained M4 overview;
    // style/channel buffers are shared with the live trace and were deleted
    // above exactly once.
    if (g._decimatedRefined) {
      this._deleteBuffers(g._homeDecimated, ["xBuf", "yBuf", "baseBuf"]);
    }
    this._deleteBuffers(g.drill, TRACE_GPU_BUFFERS);
    const textures = [];
    if (g.heatmap) textures.push(g.heatmap.tex);
    for (const d of g.densityCache || []) textures.push(d && d.tex);
    if (g.density) textures.push(g.density.tex);
    if (g._shownDensity) textures.push(g._shownDensity.tex);
    // Mid-hover the plane's ORIGINAL texture lives only here (density.tex is
    // the dimmed one), and the paths that destroy a live trace — append,
    // spec swap, animation — do not clear legend hover first.
    textures.push(g._legendHoverTex, g._legendHoverPrevTex);
    for (const tex of textures) {
      if (tex && !texSeen.has(tex)) {
        texSeen.add(tex);
        this.gl.deleteTexture(tex);
      }
    }
    g.drill = null;
    g.density = null;
    g._shownDensity = null;
    g._legendHoverTex = null;
    g._legendHoverPrevTex = null;
    g.densityCache = [];
    g.heatmap = null;
    g._cpu = null;
    g._homeDecimated = null;
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
    if (this.quad && !this._glHost) gl.deleteBuffer(this.quad);
    this.quad = null;
    if (this.quadVao && !this._glHost) gl.deleteVertexArray(this.quadVao);
    this.quadVao = null;
    for (const p of this._progCache ? this._progCache.values() : []) {
      if (p) gl.deleteProgram(p);
    }
    if (this._progCache) this._progCache.clear();
    this._glPrograms = this._progCache;
    this.gpuTraces = [];
  }
}
