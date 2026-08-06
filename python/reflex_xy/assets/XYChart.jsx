// XYChart: mount a xy figure inside a Reflex app.
//
// Two modes (spec/design/reflex-integration.md). A live subscription has
// two spellings that reduce to one token: `figure` ({token} — the typed
// FigureHandle) and the deprecated bare `token` string.
//
// Live — this component does NOT open its own connection.
// socket.io multiplexing reuses the app's engine.io websocket when the
// manager options match, so `xySocket()` below constructs its `/_xy`
// namespace socket with exactly the options Reflex's own `connect()` uses
// (`$/utils/state`). Whichever side runs first creates the shared manager;
// the other rides it. One TCP connection carries app state and chart data —
// same lifecycle, same auth surface, same proxy config.
//
// Live data protocol (namespace.py):
//   out:  sub {fig, px, mid} | unsub {fig, mid} | msg {fig, v?, mid, m}
//   in:   payload {fig, version, spec, buffers, mid?} — direct replies carry mid
//         msg {fig, version?, mid?, message, buffers} — replies carry our mid
//         err {fig, error, resync?}
// A subscribe/reconnect starts a version epoch: no msg is applied until its
// authoritative payload arrives. Replies and room-wide pushes carry the
// FigureEntry version whose data they were built against.
//
// `src` (static) — the payload was compiled ahead of time into a binary
// XYBF asset (payload_asset.py). Fetch it, decode the frame, and run the
// render client kernel-less: renderStandalone retains CPU columns so hover
// resolves locally, and density traces refine via the bundled worker. No
// socket, no backend — works under `reflex export`.
//
// The chart client itself is the same ESM bundle notebooks use (a byte-exact
// sibling copy, ./xy_client.js). Its `comm` seam is fed from socket events;
// binary columns arrive as ArrayBuffers and go straight to the GL path.

import {
  Children, cloneElement, isValidElement, useEffect, useRef, useState,
} from "react";
// Reflex compiles style props to emotion's `css`; rendering through
// emotion's jsx() (a guaranteed app dependency) honors it without relying
// on any jsxImportSource configuration in the app's build.
import { jsx } from "@emotion/react";
import io from "socket.io-client";
import env from "$/env.json";
import reflexEnvironment from "$/reflex.json";
import { getBackendURL, getToken } from "$/utils/state";
import { ChartView, decodeFrame, renderStandalone } from "./xy_client.js";

// Opt-in console tracing: localStorage.setItem("xy_debug", "1")
const DEBUG = globalThis.localStorage?.getItem?.("xy_debug") === "1";
const HOVER_THROTTLE_MS = 120;
const VIEW_THROTTLE_MS = 120;
const DEFERRED_STATE_PUSH_TYPES = new Set(["state_patch", "view_nav", "selection_rows"]);
const dbg = (...args) =>
  DEBUG &&
  console.log(
    "[xy]",
    ...args.map((a) => (typeof a === "object" && a !== null ? JSON.stringify(a) : a)),
  );
dbg("XYChart module loaded");

let sharedSocket = null;
// fig token -> number of mounted charts using it (unsub only at zero, since
// room membership is per-connection, not per-mount).
const subCounts = new Map();

function xySocket() {
  if (sharedSocket) return sharedSocket;
  const endpoint = getBackendURL(env.EVENT);
  const nsUrl = new URL(endpoint.href);
  // The URI pathname selects the socket.io *namespace*; the engine.io mount
  // path stays the app's (`endpoint.pathname`), which is what keys the
  // manager cache — same key as Reflex's socket, hence one physical ws.
  nsUrl.pathname = "/_xy";
  nsUrl.search = "";
  sharedSocket = io(nsUrl.href, {
    path: endpoint.pathname,
    transports: [env.TRANSPORT],
    protocols: [reflexEnvironment.version],
    autoUnref: false,
    query: { token: getToken() },
    reconnection: false, // the app plane owns manager reconnects
  });
  sharedSocket.on("connect", () => dbg("xy namespace connected"));
  sharedSocket.on("connect_error", (e) => dbg("xy connect_error", String(e)));
  return sharedSocket;
}

let nextMountId = 1;

// Reflex owns the mount's CSS dimensions. Payload dimensions are useful for
// standalone exports, but inside a component they must follow that mount or a
// fixed payload can paint beyond the space Reflex reserved in the page flow.
const fitSpecToElement = (spec) => ({
  ...spec,
  width: "100%",
  height: "100%",
});

const eventSpec = (spec, callbacks) => {
  const fitted = fitSpecToElement(spec);
  if (!callbacks.onPointClick && !callbacks.onViewChange) return fitted;
  const interaction = { ...(fitted.interaction || {}) };
  if (callbacks.onPointClick && interaction.click === undefined) interaction.click = true;
  if (callbacks.onViewChange && interaction.view_change === undefined) {
    interaction.view_change = true;
  }
  return { ...fitted, interaction };
};

// Payload metadata is JSON-like, but key insertion order is not part of its
// meaning. Compare it structurally so a republish only rebuilds constructor-
// owned chrome when one of its inputs actually changed.
const samePayloadValue = (left, right) => {
  if (Object.is(left, right)) return true;
  if (
    left === null || right === null ||
    typeof left !== "object" || typeof right !== "object" ||
    Array.isArray(left) !== Array.isArray(right)
  ) {
    return false;
  }
  if (Array.isArray(left)) {
    return left.length === right.length &&
      left.every((value, index) => samePayloadValue(value, right[index]));
  }
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  return leftKeys.length === rightKeys.length &&
    leftKeys.every(
      (key) =>
        Object.prototype.hasOwnProperty.call(right, key) &&
        samePayloadValue(left[key], right[key]),
    );
};

const legendTraceSpec = (trace) => {
  const color = trace?.color;
  const style = trace?.style;
  return {
    id: trace?.id ?? null,
    kind: trace?.kind ?? null,
    name: trace?.name ?? null,
    color: color
      ? {
          mode: color.mode ?? null,
          color: color.color ?? null,
          label: color.label ?? null,
          categories: color.categories ?? null,
          palette: color.palette ?? null,
          colormap: color.colormap ?? null,
        }
      : null,
    style: style
      ? {
          color: style.color ?? null,
          symbol: style.symbol ?? null,
          stroke_width: style.stroke_width ?? null,
          width: style.width ?? null,
          dash: style.dash ?? null,
        }
      : null,
  };
};

const axisLayoutSpec = (spec) => {
  const axes = { ...(spec?.axes || {}) };
  if (spec?.x_axis) axes.x = spec.x_axis;
  if (spec?.y_axis) axes.y = spec.y_axis;
  return Object.fromEntries(
    Object.entries(axes).map(([id, axis]) => [
      id,
      {
        side: axis?.side ?? null,
        tick_label_strategy: axis?.tick_label_strategy ?? null,
      },
    ]),
  );
};

// updatePayload owns new axes/ranges, trace buffers, marks, annotations,
// tooltip content, and animation. The fields below instead determine DOM
// topology or layout built only by the ChartView constructor. Projecting just
// those inputs preserves the fast path for an ordinary data-only publish while
// still rebuilding title/legend/colorbar/badge/modebar/axis-band chrome.
const mountedChromeSpec = (spec) => ({
  dom: spec?.dom ?? null,
  title: spec?.title ?? null,
  padding: spec?.padding ?? null,
  show_legend: spec?.show_legend !== false,
  legend: spec?.legend ?? null,
  extra_legends: spec?.extra_legends ?? null,
  legend_traces: (spec?.traces || []).map(legendTraceSpec),
  colorbar: spec?.colorbar ?? null,
  has_density_badges: (spec?.traces || []).some((trace) => trace?.tier === "density"),
  show_modebar: spec?.show_modebar !== false,
  export: spec?.export ?? null,
  interaction: spec?.interaction ?? null,
  axes: axisLayoutSpec(spec),
});

const sameMountedChromeSpec = (left, right) =>
  samePayloadValue(mountedChromeSpec(left), mountedChromeSpec(right));

const selectionRequest = (selection) => {
  if (selection?.range) {
    const { x0, x1, y0, y1 } = selection.range;
    return { type: "select", x0, x1, y0, y1 };
  }
  if (selection?.polygon) {
    return {
      type: "select_polygon",
      points: selection.polygon.map((point) => [...point]),
    };
  }
  return null;
};

const selectionFromRequest = (request) => {
  if (request?.type === "select") {
    return {
      range: {
        x0: request.x0,
        x1: request.x1,
        y0: request.y0,
        y1: request.y1,
        ...(request.mode === "x" || request.mode === "y" ? { mode: request.mode } : {}),
      },
    };
  }
  if (request?.type === "select_polygon") {
    return { polygon: request.points.map((point) => [...point]) };
  }
  return null;
};

const changedFromHome = (state, home) => {
  const ranges = state?.ranges;
  if (!ranges || typeof ranges !== "object") return false;
  return Object.entries(ranges).some(([axisId, range]) => {
    const homeRange = home?.ranges?.[axisId];
    return !Array.isArray(homeRange) ||
      !Array.isArray(range) ||
      range.length !== homeRange.length ||
      range.some((value, index) => value !== homeRange[index]);
  });
};

const pointEnvelope = (type, token, row, extra = {}) => {
  const { trace, index, x, y, ...datum } = row;
  return {
    version: 1,
    type,
    token,
    trace,
    canonical_row_id: index,
    data: { x, y },
    datum,
    ...extra,
  };
};

export function XYChart(props) {
  const {
    token,
    figure,
    src,
    onPointHover,
    onPointClick,
    onSelectEnd,
    onViewChange,
    onHover,
    onAnimationStart,
    onAnimationEnd,
    // Compile-time-only literal scanned by Reflex's TailwindV4Plugin. The
    // runtime chart receives the same classes from its XYBF payload; keeping
    // this prop out of divProps prevents an unknown attribute or class leak.
    tailwindClassTokens: _tailwindClassTokens,
    ref: externalRef, // reflex attaches its own ref to id-bearing components
    children,
    ...divProps
  } = props;
  void _tailwindClassTokens;
  // One subscription token from the two live spellings. `figure` is the
  // typed handle ({token}); the bare `token` string is the deprecated wire.
  // A present handle always wins — its empty token means "not ready" (no
  // subscription yet), never a fallback to the legacy spelling.
  const liveToken = figure != null ? figure.token || null : token || null;
  const elRef = useRef(null); // inner chart mount (wiped on payload swaps)
  const outerRef = useRef(null); // stable wrapper: events, tooltip slot
  const tooltipSlotRef = useRef(null);
  // Live §7.1 payload for the mounted tooltip children (null until first
  // hover). State, not a ref: the custom renderer re-renders per hover.
  const [hoverPayload, setHoverPayload] = useState(null);
  const hasTooltipChildrenRef = useRef(false);
  hasTooltipChildrenRef.current = Boolean(children);
  dbg("render", { id: divProps.id, token: String(liveToken).slice(0, 30), src });
  // Live callback refs so socket handlers never close over stale props.
  const cbRef = useRef({});
  cbRef.current = {
    onPointHover, onPointClick, onSelectEnd, onViewChange, onHover,
    onAnimationStart, onAnimationEnd,
  };

  // The structured on_hover prop needs the client's hover event surface; the
  // chart's spec may not have asked for it, so flip the switch locally
  // (spec objects are per-mount copies — see fitSpecToElement).
  const withHoverFlag = (spec) =>
    cbRef.current.onHover
      ? { ...spec, interaction: { ...spec.interaction, hover: true } }
      : spec;

  // Re-adopt the tooltip slot into a freshly built view: setCustomTooltip
  // moves the slot node inside the chart root, so it must be rescued before
  // the mount element is wiped (see reclaimTooltipSlot below).
  const mountTooltipSlot = (view) => {
    const slot = tooltipSlotRef.current;
    if (slot && view?.setCustomTooltip) view.setCustomTooltip(slot);
  };
  const reclaimTooltipSlot = () => {
    const slot = tooltipSlotRef.current;
    if (slot && outerRef.current && slot.parentElement !== outerRef.current) {
      slot.style.display = "none";
      outerRef.current.appendChild(slot);
    }
  };

  useEffect(() => {
    const el = outerRef.current;
    if (!el) return undefined;
    const start = (event) => cbRef.current.onAnimationStart?.(event.detail);
    const end = (event) => cbRef.current.onAnimationEnd?.(event.detail);
    // view-state.md §7.1: the full payload rides the client's hover/leave
    // events (bubbling CustomEvents), resolved without any kernel.
    const hover = (event) => {
      const d = event.detail || {};
      if (d.cursor) {
        const payload = {
          active: true,
          cursor: d.cursor,
          points: d.points || [],
          exact: d.exact === true,
        };
        cbRef.current.onHover?.(payload);
        // The mounted tooltip children render from this payload (§7.2);
        // skip the re-render churn when no custom renderer is mounted.
        if (hasTooltipChildrenRef.current) setHoverPayload(payload);
      }
    };
    const leave = () => {
      cbRef.current.onHover?.({ active: false, cursor: null, points: [] });
      if (hasTooltipChildrenRef.current) setHoverPayload(null);
    };
    el.addEventListener("xy:animation_start", start);
    el.addEventListener("xy:animation_end", end);
    el.addEventListener("xy:hover", hover);
    el.addEventListener("xy:leave", leave);
    return () => {
      el.removeEventListener("xy:animation_start", start);
      el.removeEventListener("xy:animation_end", end);
      el.removeEventListener("xy:hover", hover);
      el.removeEventListener("xy:leave", leave);
    };
  }, []);

  // Static mode: fetch the payload asset, render kernel-less.
  useEffect(() => {
    const el = elRef.current;
    if (!src || !el) return undefined;
    const key = outerRef.current?.id || `src:${src}`;
    let view = null;
    let cancelled = false;
    const controller = new AbortController();
    const handleViewChange = (event) => cbRef.current.onViewChange?.(event.detail);
    el.addEventListener("xy:view_change", handleViewChange);
    fetch(src, { signal: controller.signal })
      .then((resp) => {
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return resp.arrayBuffer();
      })
      .then((body) => {
        if (cancelled) return;
        const frame = decodeFrame(body);
        el.replaceChildren();
        // Same call the static HTML export makes: spec + one packed blob
        // span, comm = null → local hover columns + worker density re-bin.
        view = renderStandalone(
          el, withHoverFlag(fitSpecToElement(frame.message)), frame.buffers[0]);
        mountTooltipSlot(view);
        (window.__xy_views ||= new Map()).set(key, view);
        dbg("static payload mounted", { src, bytes: body.byteLength });
      })
      .catch((err) => {
        if (!cancelled) console.warn(`xy: static payload failed for ${src}`, err);
      });
    return () => {
      cancelled = true;
      controller.abort();
      reclaimTooltipSlot();
      if (view) view.destroy();
      view = null;
      window.__xy_views?.delete(key);
      el.removeEventListener("xy:view_change", handleViewChange);
      el.replaceChildren();
    };
  }, [src]);

  // Live mode: subscribe on the shared websocket.
  useEffect(() => {
    const el = elRef.current;
    dbg("effect run", { token: liveToken && liveToken.slice(0, 24), hasEl: !!el });
    if (!liveToken || src || !el) return undefined;
    const socket = xySocket();
    const mid = `m${nextMountId++}`;
    let view = null;
    let destroyed = false;
    let clickSeq = 0;
    let lastSelect = null;
    let payloadVersion = null;
    let pendingClickInput = null;
    const clickInputs = new Map();
    let hoverTimer = null;
    let pendingHover = null;
    let viewTimer = null;
    let pendingView = null;
    let selectionSeq = 0;
    const pendingSelectionSeqs = new Set();
    const restoreSelectionSeqs = new Set();
    const invalidatedSelectionSeqs = new Set();
    const viewCallbacks = [];
    const pendingStatePushes = [];
    let awaitingPayload = true;

    const resetEpoch = () => {
      // Timer callbacks capture row/domain data from the preceding figure
      // generation. Cancel them as part of the same reset as wire-version and
      // synthetic-reply bookkeeping so no old epoch can update Reflex state.
      if (hoverTimer !== null) clearTimeout(hoverTimer);
      if (viewTimer !== null) clearTimeout(viewTimer);
      hoverTimer = null;
      viewTimer = null;
      pendingHover = null;
      pendingView = null;
      pendingClickInput = null;
      payloadVersion = null;
      awaitingPayload = true;
      clickInputs.clear();
      pendingSelectionSeqs.clear();
      restoreSelectionSeqs.clear();
      invalidatedSelectionSeqs.clear();
      pendingStatePushes.length = 0;
    };

    const subscribe = () => {
      // A reconnect can land on a fresh worker whose rebuilt figure starts at
      // version 1. Versions are monotonic only within this subscription epoch.
      resetEpoch();
      socket.emit("sub", { fig: liveToken, px: el.clientWidth || null, mid });
    };

    const emitMessage = (m) => {
      // socket.io flushes its sendBuffer before firing `connect`; never queue
      // an old-epoch request while the namespace is disconnected.
      if (awaitingPayload || !socket.connected) return;
      const envelope = { fig: liveToken, mid, m };
      if (payloadVersion !== null) envelope.v = payloadVersion;
      socket.emit("msg", envelope);
    };

    const withSelectionSeq = (m) => ({
      ...m,
      seq: `selection:${++selectionSeq}`,
    });

    const restoreSelectionMask = (request) => {
      if (!request) return;
      const restore = withSelectionSeq(
        cbRef.current.onSelectEnd
          ? { ...request, include_rows: true }
          : request,
      );
      pendingSelectionSeqs.add(restore.seq);
      restoreSelectionSeqs.add(restore.seq);
      emitMessage(restore);
    };

    const hydrateSelectionForRepublish = (selection) => {
      if (!selection || !view) return false;
      const applied = view._applyStatePatch?.(
        { v: 1, selection },
        {
          source: "republish",
          history: false,
          dispatch: false,
          broadcast: false,
        },
      );
      if (applied === true) {
        view._restoreSelectionLocalMask?.(selection, { localMask: true });
      }
      return applied === true;
    };

    const dispatchHover = (row) => {
      pendingHover = row;
      if (hoverTimer !== null) return;
      hoverTimer = setTimeout(() => {
        hoverTimer = null;
        const latest = pendingHover;
        pendingHover = null;
        if (!destroyed && latest && cbRef.current.onPointHover) {
          cbRef.current.onPointHover(pointEnvelope("point_hover", liveToken, latest));
        }
      }, HOVER_THROTTLE_MS);
    };

    const emitView = (m) => {
      if (destroyed || !m || !cbRef.current.onViewChange) return;
      cbRef.current.onViewChange({
        version: 1,
        type: "view_change",
        token: liveToken,
        x_domain: [m.x0, m.x1],
        y_domain: [m.y0, m.y1],
        source: m.source,
        phase: m.phase === "update" ? "update" : "final",
      });
    };

    // Leading + trailing throttle, latest-wins: the first event of a gesture
    // dispatches immediately so on_view_change-driven charts track pan/zoom
    // live; the trailing flush guarantees the resting "final" view lands.
    const openViewWindow = () => {
      viewTimer = setTimeout(() => {
        viewTimer = null;
        if (pendingView !== null) {
          const latest = pendingView;
          pendingView = null;
          emitView(latest);
          openViewWindow();
        }
      }, VIEW_THROTTLE_MS);
    };

    const dispatchView = (m) => {
      // The old ChartView can still receive gestures while a reconnect/full
      // resync is waiting for its authoritative payload. Do not let that
      // preceding epoch arm a new trailing timer after resetEpoch cleared it.
      if (
        awaitingPayload
        || !socket.connected
        || !cbRef.current.onViewChange
        || m.source === "linked"
        || m.source === "republish"
      ) return;
      if (viewTimer === null) {
        emitView(m);
        openViewWindow();
      } else {
        pendingView = m;
      }
    };

    const comm = {
      send: (m) => {
        if (!m || destroyed) return;
        if (m.type === "view_change") {
          // Semantic event, resolved locally — the kernel round-trip would
          // be a no-op (the namespace registers no Python-side callbacks).
          dispatchView(m);
          return;
        }
        if (awaitingPayload || !socket.connected) return;
        if (m.type === "select" || m.type === "select_polygon" || m.type === "select_clear") {
          m = withSelectionSeq(m);
          pendingSelectionSeqs.add(m.seq);
          lastSelect = m.type === "select_clear" ? null : m;
          if (cbRef.current.onSelectEnd) m = { ...m, include_rows: true };
        }
        emitMessage(m);
        if (m.type === "click" && cbRef.current.onPointClick) {
          // The kernel's click path resolves rows via pick; ask for the row
          // with a tagged seq the reply routing below consumes.
          clickSeq += 1;
          const seq = `click:${clickSeq}`;
          clickInputs.set(seq, pendingClickInput || {
            screen: m.screen || { x: null, y: null },
            modifiers: m.modifiers || { shift: false, alt: false, ctrl: false, meta: false },
          });
          pendingClickInput = null;
          emitMessage({
            type: "pick",
            trace: m.trace,
            index: m.index,
            drill_seq: m.drill_seq,
            seq,
          });
        }
      },
      wantsViewChange: () => Boolean(cbRef.current.onViewChange),
      onMessage: (cb) => {
        viewCallbacks.push(cb);
        return () => {
          const i = viewCallbacks.indexOf(cb);
          if (i >= 0) viewCallbacks.splice(i, 1);
        };
      },
    };

    const toSpans = (spec, buffers) => {
      const spans = (buffers || []).map((b) => new Uint8Array(b));
      return spec.buffer_layout === "split" ? spans : spans[0];
    };

    const discardPendingReply = (message) => {
      if (typeof message?.seq !== "string") return;
      if (message.seq.startsWith("click:")) clickInputs.delete(message.seq);
      pendingSelectionSeqs.delete(message.seq);
      restoreSelectionSeqs.delete(message.seq);
      invalidatedSelectionSeqs.delete(message.seq);
    };

    const dispatchToView = (message, buffers) => {
      for (const cb of [...viewCallbacks]) cb(message, buffers);
    };

    const statePushGeneration = (data, message) => (
      data.mid == null &&
      Number.isInteger(data.version) &&
      DEFERRED_STATE_PUSH_TYPES.has(message.type)
        ? data.version
        : null
    );

    const selectionPushReplacesSelection = (message) =>
      message.type === "selection_rows" ||
      (
        message.type === "state_patch" &&
        Object.prototype.hasOwnProperty.call(message.state || {}, "selection")
      );

    const invalidateSelectionReplies = () => {
      for (const seq of pendingSelectionSeqs) invalidatedSelectionSeqs.add(seq);
      pendingSelectionSeqs.clear();
      restoreSelectionSeqs.clear();
    };

    const invalidatePayloadReplies = () => {
      // An addressed payload can replace px-dependent shipped rows without
      // advancing the FigureEntry generation. Replies already in flight still
      // carry that same version, so version gating alone cannot prove that
      // their indices belong to the newly mounted payload.
      pendingClickInput = null;
      clickInputs.clear();
      invalidateSelectionReplies();
    };

    const deferStatePush = (data, message) => {
      // Programmatic view/selection pushes are not part of the authoritative
      // figure payload. Preserve only generation-stamped room events; replies
      // and appends remain unsafe to defer across payload mounts.
      const generation = statePushGeneration(data, message);
      if (generation !== null) {
        pendingStatePushes.push({ generation, message, buffers: data.buffers || [] });
        return true;
      }
      return false;
    };

    const replayPendingStatePushes = (payloadGeneration) => {
      const queued = pendingStatePushes.splice(0);
      for (const { generation, message, buffers } of queued) {
        if (generation === payloadGeneration) dispatchToView(message, buffers);
        else if (generation > payloadGeneration) {
          pendingStatePushes.push({ generation, message, buffers });
        }
      }
    };

    const pendingPushReplacesSelection = (payloadGeneration) =>
      pendingStatePushes.some(({ generation, message }) =>
        generation === payloadGeneration && selectionPushReplacesSelection(message)
      );

    const onPayload = (data) => {
      if (destroyed || !data || data.fig !== liveToken) return;
      // Direct subscription replies are mount-addressed; room-wide rebuild
      // broadcasts intentionally omit mid and remain visible to every mount.
      if (data.mid !== undefined && data.mid !== null && data.mid !== mid) return;
      const rowsSelectionMounted =
        view?.root?.xy?.state?.()?.selection?.rows === true;
      if (
        Number.isInteger(data.version) &&
        payloadVersion !== null &&
        data.version === payloadVersion &&
        !awaitingPayload &&
        (data.mid == null || rowsSelectionMounted)
      ) {
        // Rebuild recovery can deliver a room payload and an addressed reply
        // at the same generation. Generic duplicates have no mount-specific
        // value; an addressed payload may refine px-dependent data, except
        // when accepting it would rebuild GPU traces and erase an already
        // replayed rows mask that cannot be reconstructed from durable state.
        return;
      }
      if (
        Number.isInteger(data.version)
        && payloadVersion !== null
        && data.version < payloadVersion
      ) return;
      const nextPayloadVersion = Number.isInteger(data.version) ? data.version : null;
      const sameGenerationAddressedReplacement =
        data.mid != null &&
        payloadVersion !== null &&
        nextPayloadVersion === payloadVersion &&
        !awaitingPayload;
      if (sameGenerationAddressedReplacement) invalidatePayloadReplies();
      if (payloadVersion !== null && nextPayloadVersion !== payloadVersion) {
        // Requests stamped with the preceding version will be dropped by the
        // server. Do not retain their synthetic click/selection bookkeeping.
        clickInputs.clear();
        pendingSelectionSeqs.clear();
        restoreSelectionSeqs.clear();
        invalidatedSelectionSeqs.clear();
      }
      // The public durable-state document is the authoritative client mirror:
      // unlike `lastSelect`, it includes linked selections, x/y band mode, and
      // every named axis range. Fall back only for an older client bundle that
      // predates the state handle.
      const durableState = view?.root?.xy?.state?.() || null;
      const previousView = durableState?.ranges
        ? { ranges: durableState.ranges, source: "republish" }
        : view?._eventView?.("republish") || null;
      const viewChanged = changedFromHome(
        durableState || (previousView?.ranges ? { ranges: previousView.ranges } : null),
        view?.view0,
      );
      const selectionToRestore = durableState
        ? durableState.selection
        : selectionFromRequest(lastSelect);
      // A queued select/clear/rows push is newer than the pre-payload client
      // selection. Do not send a restore request whose later async reply could
      // overwrite that queued replacement after it is replayed below.
      const selectionMaskRequest = pendingPushReplacesSelection(nextPayloadVersion)
        ? null
        : selectionRequest(selectionToRestore);
      payloadVersion = nextPayloadVersion;
      const spec = withHoverFlag(eventSpec(data.spec, cbRef.current));
      const nextBuffers = toSpans(data.spec, data.buffers);
      const chromeChanged = Boolean(view && !sameMountedChromeSpec(view.spec, spec));
      if (!chromeChanged && view?.updatePayload?.(spec, nextBuffers)) {
        // updatePayload re-homes the viewport and rebuilds trace state, so pin
        // the domain and re-request the selection mask after the in-place swap.
        if (viewChanged) {
          view._transitionView = null;
          view._setView(previousView, { animate: false, source: "republish" });
        }
        if (selectionMaskRequest) {
          hydrateSelectionForRepublish(selectionToRestore);
        }
        awaitingPayload = false;
        restoreSelectionMask(selectionMaskRequest);
        replayPendingStatePushes(nextPayloadVersion);
        return;
      }
      reclaimTooltipSlot();
      if (view) view.destroy();
      viewCallbacks.length = 0;
      el.replaceChildren();
      view = new ChartView(
        el,
        spec,
        nextBuffers,
        comm,
      );
      mountTooltipSlot(view);
      if (viewChanged) {
        view._setView(previousView, { animate: false, source: "republish" });
      }
      if (selectionMaskRequest) {
        // Hydrate durable geometry plus a provisional local mask before the
        // eventual authoritative reply, without replaying the user gesture.
        hydrateSelectionForRepublish(selectionToRestore);
      }
      awaitingPayload = false;
      restoreSelectionMask(selectionMaskRequest);
      // Debug/e2e handle (same spirit as the standalone example's
      // window.xyLiveDrilldown): headless probes assert on live views.
      (window.__xy_views ||= new Map()).set(outerRef.current?.id || mid, view);
      replayPendingStatePushes(nextPayloadVersion);
    };

    const onMsg = (data) => {
      if (destroyed || !data || data.fig !== liveToken) return;
      // Replies are mount-addressed; pushes (append) carry no mid.
      if (data.mid !== undefined && data.mid !== null && data.mid !== mid) return;
      const message = data.message;
      if (!message) return;
      if (awaitingPayload) {
        if (!deferStatePush(data, message)) discardPendingReply(message);
        return;
      }
      const wireVersion = Number.isInteger(data.version) ? data.version : null;
      const deferredPushGeneration = statePushGeneration(data, message);
      if (
        deferredPushGeneration !== null &&
        payloadVersion !== null &&
        deferredPushGeneration > payloadVersion
      ) {
        // A post-mutation state write can overtake either the matching append
        // or a replacement payload. Keep it until that generation mounts;
        // unlike a reply, it remains authoritative room state.
        if (selectionPushReplacesSelection(message)) invalidateSelectionReplies();
        deferStatePush(data, message);
        return;
      }
      if (wireVersion !== null && payloadVersion !== null) {
        const isAppendPush = message.type === "append" && data.mid == null;
        const expected = isAppendPush
          ? payloadVersion + 1
          : payloadVersion;
        if (wireVersion !== expected) {
          discardPendingReply(message);
          // A forward gap means at least one append was not applied (for
          // example, an oversized binary push). Re-prime from a full payload
          // instead of rejecting every subsequent append forever.
          if (isAppendPush && wireVersion > expected && socket.connected) subscribe();
          return;
        }
      }
      if (
        data.mid == null &&
        DEFERRED_STATE_PUSH_TYPES.has(message.type) &&
        selectionPushReplacesSelection(message)
      ) invalidateSelectionReplies();
      let clientMessage = message;
      if (typeof message.seq === "string" && message.seq.startsWith("click:")) {
        const clickWasPending = clickInputs.has(message.seq);
        const clickInput = clickInputs.get(message.seq);
        clickInputs.delete(message.seq);
        if (!clickWasPending) return;
        if (message.type === "pick_result" && message.row) {
          cbRef.current.onPointClick?.(
            pointEnvelope("point_click", liveToken, message.row, clickInput || {}),
          );
        }
        return; // synthetic pick — not for the view
      }
      if (message.type === "pick_result" && message.row) {
        if (cbRef.current.onPointHover) dispatchHover(message.row);
      }
      if (message.type === "selection") {
        const selectionWasInvalidated = invalidatedSelectionSeqs.delete(message.seq);
        const selectionWasPending = pendingSelectionSeqs.delete(message.seq);
        if (selectionWasInvalidated || !selectionWasPending) return;
        const isRestore = restoreSelectionSeqs.delete(message.seq);
        // The mask reply still has to reach ChartView, but this restore was
        // initiated by a payload swap rather than a new user gesture. Tag the
        // client-only copy so it applies buffers without emitting xy:select;
        // the Reflex callback is suppressed by the same sequence check below.
        if (isRestore) clientMessage = { ...message, suppress_event: true };
        if (!isRestore && cbRef.current.onSelectEnd) {
          const cleared = message.total === 0 && lastSelect === null;
          const fallbackBounds = lastSelect && lastSelect.type === "select"
            ? { x0: lastSelect.x0, x1: lastSelect.x1, y0: lastSelect.y0, y1: lastSelect.y1 }
            : null;
          cbRef.current.onSelectEnd({
            version: 1,
            type: "select_end",
            token: liveToken,
            selection: {
              kind: cleared ? "clear" : (message.kind || "box"),
              mode: message.mode || "replace",
              data_bounds: message.bounds || fallbackBounds,
              polygon: message.polygon
                || (lastSelect?.type === "select_polygon" ? lastSelect.points : null),
              canonical_row_ids: message.canonical_row_ids || [],
              rows: message.rows || [],
              total_count: message.total ?? 0,
              truncated: message.truncated === true,
              cleared,
            },
          });
        }
      }
      if (wireVersion !== null && message.type === "append" && data.mid == null) {
        clickInputs.clear();
        pendingSelectionSeqs.clear();
        restoreSelectionSeqs.clear();
        invalidatedSelectionSeqs.clear();
        payloadVersion = wireVersion;
        // The append establishes the generation whose state writes may have
        // reached this mount first. Apply the data delta before replaying
        // those writes so row-backed selections see the new trace lengths.
        dispatchToView(clientMessage, data.buffers || []);
        replayPendingStatePushes(wireVersion);
        return;
      }
      dispatchToView(clientMessage, data.buffers || []);
    };

    const onErr = (data) => {
      if (destroyed || !data || data.fig !== liveToken) return;
      console.warn(`xy: ${data.error} (fig ${data.fig})`);
      if (data.resync === true && socket.connected) subscribe();
    };

    const onDisconnect = () => {
      resetEpoch();
    };

    socket.on("payload", onPayload);
    socket.on("msg", onMsg);
    socket.on("err", onErr);
    socket.on("disconnect", onDisconnect);
    // Resubscribe on every (re)connect: after the app plane reconnects the
    // shared manager, rooms are gone and — on another backend node — the
    // figure itself may need a state-driven rebuild. `sub` triggers both.
    socket.on("connect", subscribe);
    subCounts.set(liveToken, (subCounts.get(liveToken) || 0) + 1);
    if (socket.connected) subscribe();

    const rememberClick = (event) => {
      if (!cbRef.current.onPointClick) return;
      const rect = view?.canvas?.getBoundingClientRect?.() || el.getBoundingClientRect();
      pendingClickInput = {
        screen: {
          x: Number.isFinite(event.clientX) ? event.clientX - rect.left : null,
          y: Number.isFinite(event.clientY) ? event.clientY - rect.top : null,
        },
        modifiers: {
          shift: event.shiftKey === true,
          alt: event.altKey === true,
          ctrl: event.ctrlKey === true,
          meta: event.metaKey === true,
        },
      };
    };
    const tracksClickInput = Boolean(cbRef.current.onPointClick);
    if (tracksClickInput) el.addEventListener("click", rememberClick, true);

    return () => {
      destroyed = true;
      if (tracksClickInput) el.removeEventListener("click", rememberClick, true);
      resetEpoch();
      socket.off("payload", onPayload);
      socket.off("msg", onMsg);
      socket.off("err", onErr);
      socket.off("disconnect", onDisconnect);
      socket.off("connect", subscribe);
      const remaining = (subCounts.get(liveToken) || 1) - 1;
      if (remaining <= 0) {
        subCounts.delete(liveToken);
        if (socket.connected) socket.emit("unsub", { fig: liveToken, mid });
      } else {
        subCounts.set(liveToken, remaining);
      }
      reclaimTooltipSlot();
      if (view) view.destroy();
      view = null;
      window.__xy_views?.delete(outerRef.current?.id || mid);
      el.replaceChildren();
    };
  }, [liveToken, src]);

  // One DOM node, two consumers: our mount logic and reflex's ref registry.
  const mergedRef = (node) => {
    outerRef.current = node;
    if (typeof externalRef === "function") externalRef(node);
    else if (externalRef) externalRef.current = node;
  };
  // Children are the framework-owned tooltip content (view-state.md §7.2):
  // they render into a hidden slot beside the chart mount; setCustomTooltip
  // adopts the slot into the chart's tooltip container, which owns placement.
  // Recharts-style render contract: each element child is cloned with the
  // live §7.1 payload as props ({active, cursor, points, exact}), so the
  // renderer receives hover data client-side with no backend bridge — the
  // slot node moves under the tooltip container, but React keeps updating
  // its subtree by node identity. DOM-tag children (plain divs) are left
  // uncloned to avoid leaking non-DOM attributes.
  const tooltipPayload = hoverPayload || { active: false, cursor: null, points: [] };
  const tooltipChildren = children
    ? Children.map(children, (child) =>
        isValidElement(child) && typeof child.type !== "string"
          ? cloneElement(child, {
              active: tooltipPayload.active,
              cursor: tooltipPayload.cursor,
              points: tooltipPayload.points,
              exact: tooltipPayload.exact === true,
            })
          : child)
    : null;
  return jsx(
    "div",
    { ...divProps, ref: mergedRef, style: { position: "relative", ...divProps.style } },
    jsx("div", { ref: elRef, style: { width: "100%", height: "100%" } }),
    children
      ? jsx(
          "div",
          {
            ref: (node) => { tooltipSlotRef.current = node; },
            "data-xy-tooltip-slot": "",
            style: { display: "none" },
          },
          tooltipChildren,
        )
      : null,
  );
}
