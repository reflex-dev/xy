// XYChart: mount a xy figure inside a Reflex app.
//
// Transport (docs/design/reflex-integration.md): this component does NOT open
// its own connection. socket.io multiplexing reuses the app's engine.io
// websocket when the manager options match, so `xySocket()` below constructs
// its `/_xy` namespace socket with exactly the options Reflex's own
// `connect()` uses (`$/utils/state`). Whichever side runs first creates the
// shared manager; the other rides it. One TCP connection carries app state
// and chart data — same lifecycle, same auth surface, same proxy config.
//
// Data protocol (namespace.py):
//   out:  sub {fig, px, mid} | unsub {fig, mid} | msg {fig, mid, m}
//   in:   payload {fig, version, spec, buffers} — buffers are ArrayBuffers
//         msg {fig, mid?, message, buffers}     — replies carry our mid
//         err {fig, error}
//
// The chart client itself is the same ESM bundle notebooks use (a byte-exact
// sibling copy, ./xy_client.js). Its `comm` seam is fed from socket events;
// binary columns arrive as ArrayBuffers and go straight to the GL path.

import { useEffect, useRef } from "react";
// Reflex compiles style props to emotion's `css`; rendering through
// emotion's jsx() (a guaranteed app dependency) honors it without relying
// on any jsxImportSource configuration in the app's build.
import { jsx } from "@emotion/react";
import io from "socket.io-client";
import env from "$/env.json";
import reflexEnvironment from "$/reflex.json";
import { getBackendURL, getToken } from "$/utils/state";
import { ChartView } from "./xy_client.js";

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

export function XYChart(props) {
  const {
    token,
    onPointHover,
    onPointClick,
    onSelectEnd,
    onViewChange,
    ref: externalRef, // reflex attaches its own ref to id-bearing components
    ...divProps
  } = props;
  const elRef = useRef(null);
  dbg("render", { id: divProps.id, tokenType: typeof token, token: String(token).slice(0, 30) });
  // Live callback refs so socket handlers never close over stale props.
  const cbRef = useRef({});
  cbRef.current = { onPointHover, onPointClick, onSelectEnd, onViewChange };

  useEffect(() => {
    const el = elRef.current;
    dbg("effect run", { token: token && token.slice(0, 24), hasEl: !!el });
    if (!token || !el) return undefined;
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
        if (m.type === "select" || m.type === "select_clear") {
          lastSelect = m.type === "select" ? m : null;
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
      if (view) view.destroy();
      viewCallbacks.length = 0;
      el.replaceChildren();
      view = new ChartView(el, data.spec, toSpans(data.spec, data.buffers), comm);
      // Debug/e2e handle (same spirit as the standalone example's
      // window.xyLiveDrilldown): headless probes assert on live views.
      (window.__xy_views ||= new Map()).set(el.id || mid, view);
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
      if (view) view.destroy();
      view = null;
      window.__xy_views?.delete(el.id || mid);
      el.replaceChildren();
    };
  }, [token]);

  // One DOM node, two consumers: our mount logic and reflex's ref registry.
  const mergedRef = (node) => {
    elRef.current = node;
    if (typeof externalRef === "function") externalRef(node);
    else if (externalRef) externalRef.current = node;
  };
  return jsx("div", { ...divProps, ref: mergedRef });
}
