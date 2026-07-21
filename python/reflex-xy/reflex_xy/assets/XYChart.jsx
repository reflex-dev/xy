// XYChart: mount a xy figure inside a Reflex app.
//
// Two modes, one prop apart (spec/design/reflex-integration.md):
//
// `token` (live) — this component does NOT open its own connection.
// socket.io multiplexing reuses the app's engine.io websocket when the
// manager options match, so `xySocket()` below constructs its `/_xy`
// namespace socket with exactly the options Reflex's own `connect()` uses
// (`$/utils/state`). Whichever side runs first creates the shared manager;
// the other rides it. One TCP connection carries app state and chart data —
// same lifecycle, same auth surface, same proxy config.
//
// Live data protocol (namespace.py):
//   out:  sub {fig, px, mid} | unsub {fig, mid} | msg {fig, mid, m}
//   in:   payload {fig, version, spec, buffers} — buffers are ArrayBuffers
//         msg {fig, mid?, message, buffers}     — replies carry our mid
//         err {fig, error}
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
const VIEW_DEBOUNCE_MS = 200;
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
  const elRef = useRef(null); // inner chart mount (wiped on payload swaps)
  const outerRef = useRef(null); // stable wrapper: events, tooltip slot
  const tooltipSlotRef = useRef(null);
  // Live §7.1 payload for the mounted tooltip children (null until first
  // hover). State, not a ref: the custom renderer re-renders per hover.
  const [hoverPayload, setHoverPayload] = useState(null);
  const hasTooltipChildrenRef = useRef(false);
  hasTooltipChildrenRef.current = Boolean(children);
  dbg("render", { id: divProps.id, token: String(token).slice(0, 30), src });
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
    const handleViewChange = (event) => cbRef.current.onViewChange?.(event.detail);
    el.addEventListener("xy:view_change", handleViewChange);
    fetch(src)
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
    dbg("effect run", { token: token && token.slice(0, 24), hasEl: !!el });
    if (!token || src || !el) return undefined;
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
    const restoreSelectionSeqs = new Set();
    const viewCallbacks = [];

    const subscribe = () => {
      socket.emit("sub", { fig: token, px: el.clientWidth || null, mid });
    };

    const emitMessage = (m) => {
      const envelope = { fig: token, mid, m };
      if (payloadVersion !== null) envelope.v = payloadVersion;
      socket.emit("msg", envelope);
    };

    const withSelectionSeq = (m) => ({
      ...m,
      seq: `selection:${++selectionSeq}`,
    });

    const restoreSelection = (selection) => {
      const restore = withSelectionSeq(
        cbRef.current.onSelectEnd
          ? { ...selection, include_rows: true }
          : selection,
      );
      restoreSelectionSeqs.add(restore.seq);
      emitMessage(restore);
    };

    const dispatchHover = (row) => {
      pendingHover = row;
      if (hoverTimer !== null) return;
      hoverTimer = setTimeout(() => {
        hoverTimer = null;
        const latest = pendingHover;
        pendingHover = null;
        if (!destroyed && latest && cbRef.current.onPointHover) {
          cbRef.current.onPointHover(pointEnvelope("point_hover", token, latest));
        }
      }, HOVER_THROTTLE_MS);
    };

    const dispatchView = (m) => {
      if (!cbRef.current.onViewChange || m.source === "linked" || m.source === "republish") return;
      pendingView = m;
      if (viewTimer !== null) clearTimeout(viewTimer);
      viewTimer = setTimeout(() => {
        viewTimer = null;
        const latest = pendingView;
        pendingView = null;
        if (!destroyed && latest && cbRef.current.onViewChange) {
          cbRef.current.onViewChange({
            version: 1,
            type: "view_change",
            token,
            x_domain: [latest.x0, latest.x1],
            y_domain: [latest.y0, latest.y1],
            source: latest.source,
            phase: "final",
          });
        }
      }, VIEW_DEBOUNCE_MS);
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
        if (m.type === "select" || m.type === "select_polygon" || m.type === "select_clear") {
          m = withSelectionSeq(m);
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

    const onPayload = (data) => {
      if (destroyed || !data || data.fig !== token) return;
      const previousView = view?._eventView?.("republish") || null;
      const homeView = view?.view0 || null;
      const viewChanged = previousView && homeView && ["x0", "x1", "y0", "y1"].some(
        (key) => previousView[key] !== homeView[key],
      );
      const selectionToRestore = lastSelect;
      payloadVersion = Number.isInteger(data.version) ? data.version : null;
      const spec = withHoverFlag(eventSpec(data.spec, cbRef.current));
      const nextBuffers = toSpans(data.spec, data.buffers);
      if (view?.updatePayload?.(spec, nextBuffers)) {
        // updatePayload re-homes the viewport and rebuilds trace state, so pin
        // the domain and re-request the selection mask after the in-place swap.
        if (viewChanged) {
          view._transitionView = null;
          view._setView(previousView, { animate: false, source: "republish" });
        }
        if (selectionToRestore) {
          restoreSelection(selectionToRestore);
        }
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
      if (selectionToRestore) {
        restoreSelection(selectionToRestore);
      }
      // Debug/e2e handle (same spirit as the standalone example's
      // window.xyLiveDrilldown): headless probes assert on live views.
      (window.__xy_views ||= new Map()).set(outerRef.current?.id || mid, view);
    };

    const onMsg = (data) => {
      if (destroyed || !data || data.fig !== token) return;
      // Replies are mount-addressed; pushes (append) carry no mid.
      if (data.mid !== undefined && data.mid !== null && data.mid !== mid) return;
      const message = data.message;
      if (!message) return;
      if (typeof message.seq === "string" && message.seq.startsWith("click:")) {
        const clickInput = clickInputs.get(message.seq);
        clickInputs.delete(message.seq);
        if (message.type === "pick_result" && message.row) {
          cbRef.current.onPointClick?.(
            pointEnvelope("point_click", token, message.row, clickInput || {}),
          );
        }
        return; // synthetic pick — not for the view
      }
      if (message.type === "pick_result" && message.row) {
        if (cbRef.current.onPointHover) dispatchHover(message.row);
      }
      if (message.type === "selection") {
        const isRestore = restoreSelectionSeqs.delete(message.seq);
        if (!isRestore && cbRef.current.onSelectEnd) {
          const cleared = message.total === 0 && lastSelect === null;
          const fallbackBounds = lastSelect && lastSelect.type === "select"
            ? { x0: lastSelect.x0, x1: lastSelect.x1, y0: lastSelect.y0, y1: lastSelect.y1 }
            : null;
          cbRef.current.onSelectEnd({
            version: 1,
            type: "select_end",
            token,
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
      for (const cb of [...viewCallbacks]) cb(message, data.buffers || []);
    };

    const onErr = (data) => {
      if (destroyed || !data || data.fig !== token) return;
      console.warn(`xy: ${data.error} (fig ${data.fig})`);
    };

    socket.on("payload", onPayload);
    socket.on("msg", onMsg);
    socket.on("err", onErr);
    // Resubscribe on every (re)connect: after the app plane reconnects the
    // shared manager, rooms are gone and — on another backend node — the
    // figure itself may need a state-driven rebuild. `sub` triggers both.
    socket.on("connect", subscribe);
    subCounts.set(token, (subCounts.get(token) || 0) + 1);
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
      if (hoverTimer !== null) clearTimeout(hoverTimer);
      if (viewTimer !== null) clearTimeout(viewTimer);
      hoverTimer = null;
      viewTimer = null;
      pendingHover = null;
      pendingView = null;
      pendingClickInput = null;
      clickInputs.clear();
      restoreSelectionSeqs.clear();
      socket.off("payload", onPayload);
      socket.off("msg", onMsg);
      socket.off("err", onErr);
      socket.off("connect", subscribe);
      const remaining = (subCounts.get(token) || 1) - 1;
      if (remaining <= 0) {
        subCounts.delete(token);
        if (socket.connected) socket.emit("unsub", { fig: token, mid });
      } else {
        subCounts.set(token, remaining);
      }
      reclaimTooltipSlot();
      if (view) view.destroy();
      view = null;
      window.__xy_views?.delete(outerRef.current?.id || mid);
      el.replaceChildren();
    };
  }, [token, src]);

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
