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
    const viewCallbacks = [];

    const subscribe = () => {
      socket.emit("sub", { fig: token, px: el.clientWidth || null, mid });
    };

    const comm = {
      send: (m) => {
        if (!m || destroyed) return;
        if (m.type === "view_change") {
          // Semantic event, resolved locally — the kernel round-trip would
          // be a no-op (the namespace registers no Python-side callbacks).
          cbRef.current.onViewChange?.(m);
          return;
        }
        if (m.type === "select" || m.type === "select_polygon" || m.type === "select_clear") {
          lastSelect = m.type === "select_clear" ? null : m;
        }
        socket.emit("msg", { fig: token, mid, m });
        if (m.type === "click" && cbRef.current.onPointClick) {
          // The kernel's click path resolves rows via pick; ask for the row
          // with a tagged seq the reply routing below consumes.
          clickSeq += 1;
          socket.emit("msg", {
            fig: token,
            mid,
            m: {
              type: "pick",
              trace: m.trace,
              index: m.index,
              drill_seq: m.drill_seq,
              seq: `click:${clickSeq}`,
            },
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
      const nextSpec = withHoverFlag(fitSpecToElement(data.spec));
      const nextBuffers = toSpans(data.spec, data.buffers);
      if (view?.updatePayload?.(nextSpec, nextBuffers)) return;
      reclaimTooltipSlot();
      if (view) view.destroy();
      viewCallbacks.length = 0;
      el.replaceChildren();
      view = new ChartView(
        el,
        nextSpec,
        nextBuffers,
        comm,
      );
      mountTooltipSlot(view);
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
        if (message.type === "pick_result" && message.row) {
          cbRef.current.onPointClick?.(message.row);
        }
        return; // synthetic pick — not for the view
      }
      if (message.type === "pick_result" && message.row) {
        cbRef.current.onPointHover?.(message.row);
      }
      if (message.type === "selection" && cbRef.current.onSelectEnd) {
        cbRef.current.onSelectEnd({
          total: message.total ?? 0,
          x0: lastSelect?.x0 ?? null,
          x1: lastSelect?.x1 ?? null,
          y0: lastSelect?.y0 ?? null,
          y1: lastSelect?.y1 ?? null,
          polygon: lastSelect?.type === "select_polygon" ? lastSelect.points : null,
          cleared: message.total === 0 && lastSelect === null,
        });
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

    return () => {
      destroyed = true;
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
