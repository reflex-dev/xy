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

import { useEffect, useRef } from "react";
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
// Upper bound on how long a republish keeps the outgoing view frozen on top
// while the rebuilt one settles. Must exceed the view-request debounce plus a
// kernel round-trip; past it the swap happens regardless, settled or not.
const GHOST_SETTLE_TIMEOUT_MS = 1200;
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
    onAnimationStart,
    onAnimationEnd,
    // Compile-time-only literal scanned by Reflex's TailwindV4Plugin. The
    // runtime chart receives the same classes from its XYBF payload; keeping
    // this prop out of divProps prevents an unknown attribute or class leak.
    tailwindClassTokens: _tailwindClassTokens,
    ref: externalRef, // reflex attaches its own ref to id-bearing components
    ...divProps
  } = props;
  void _tailwindClassTokens;
  const elRef = useRef(null);
  dbg("render", { id: divProps.id, token: String(token).slice(0, 30), src });
  // Live callback refs so socket handlers never close over stale props.
  const cbRef = useRef({});
  cbRef.current = {
    onPointHover, onPointClick, onSelectEnd, onViewChange,
    onAnimationStart, onAnimationEnd,
  };

  useEffect(() => {
    const el = elRef.current;
    if (!el) return undefined;
    const start = (event) => cbRef.current.onAnimationStart?.(event.detail);
    const end = (event) => cbRef.current.onAnimationEnd?.(event.detail);
    el.addEventListener("xy:animation_start", start);
    el.addEventListener("xy:animation_end", end);
    return () => {
      el.removeEventListener("xy:animation_start", start);
      el.removeEventListener("xy:animation_end", end);
    };
  }, []);

  // Static mode: fetch the payload asset, render kernel-less.
  useEffect(() => {
    const el = elRef.current;
    if (!src || !el) return undefined;
    const key = el.id || `src:${src}`;
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
        view = renderStandalone(el, fitSpecToElement(frame.message), frame.buffers[0]);
        (window.__xy_views ||= new Map()).set(key, view);
        dbg("static payload mounted", { src, bytes: body.byteLength });
      })
      .catch((err) => {
        if (!cancelled) console.warn(`xy: static payload failed for ${src}`, err);
      });
    return () => {
      cancelled = true;
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
    let restoringSelection = false;
    // Keep the outgoing view visible while its replacement restores any
    // selection and drilled density tier. The timer bounds lost replies.
    let ghost = null;
    const settleGhost = () => {
      if (!ghost) return;
      const g = ghost;
      ghost = null;
      clearTimeout(g.timer);
      g.view.destroy();
      g.div.remove();
    };
    // The ghost shows full-alpha marks; the rebuilt view re-runs the §5
    // aggregate→marks entry fade from zero. Dropping the ghost mid-fade
    // uncovers a mostly-density frame that then brightens — a visible color
    // jump. Hold until the tier fades finish so the swap is pixel-steady.
    const ghostFadesDone = () => {
      if (!view || !view.gpuTraces) return true;
      return view.gpuTraces.every(
        (g) => g.tier !== "density"
          || (g._drillFadeStart == null && g._densitySwitchFadeStart == null),
      );
    };
    const settleGhostAfterDraw = () => {
      const step = () => {
        if (!ghost) return;
        if (ghostFadesDone()) {
          // One more frame so the settled state reaches the screen first.
          requestAnimationFrame(settleGhost);
          return;
        }
        requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    };
    const viewCallbacks = [];

    const subscribe = () => {
      socket.emit("sub", { fig: token, px: el.clientWidth || null, mid });
    };

    const emitMessage = (m) => {
      const envelope = { fig: token, mid, m };
      if (payloadVersion !== null) envelope.v = payloadVersion;
      socket.emit("msg", envelope);
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
      const spec = eventSpec(data.spec, cbRef.current);
      const nextBuffers = toSpans(data.spec, data.buffers);
      if (view?.updatePayload?.(spec, nextBuffers)) {
        // In-place data swap (animations path): the canvas never tears down,
        // so no ghost is needed — but updatePayload re-homes the viewport and
        // rebuilds trace state, so the republish restore contract still
        // applies: pin the domain (the data-animation tick would keep
        // lerping this.view otherwise) and re-request the selection mask.
        settleGhost();
        if (viewChanged) {
          view._transitionView = null;
          view._setView(previousView, { animate: false, source: "republish" });
        }
        if (selectionToRestore) {
          restoringSelection = true;
          const restore = cbRef.current.onSelectEnd
            ? { ...selectionToRestore, include_rows: true }
            : selectionToRestore;
          emitMessage(restore);
        }
        return;
      }
      settleGhost(); // a racing republish replaces the previous ghost
      const hasDensity = (data.spec.traces || []).some((t) => t.tier === "density");
      if (view) {
        // Freeze the outgoing view on top; the rebuilt one settles under it.
        // The ghost is inert (no comm subscription after the reset below, no
        // pointer events) — it just keeps its last frame visible.
        const div = document.createElement("div");
        div.style.cssText =
          "position:absolute;inset:0;z-index:2;pointer-events:none;";
        div.dataset.xyRepublishGhost = "";
        div.append(...el.childNodes);
        el.appendChild(div);
        if (!el.style.position) el.style.position = "relative";
        ghost = {
          div,
          view,
          selectionPending: Boolean(selectionToRestore),
          densityPending: Boolean(hasDensity && viewChanged),
          timer: setTimeout(settleGhost, GHOST_SETTLE_TIMEOUT_MS),
        };
      } else {
        el.replaceChildren();
      }
      viewCallbacks.length = 0;
      view = new ChartView(
        el,
        spec,
        nextBuffers,
        comm,
      );
      if (viewChanged) {
        view._setView(previousView, { animate: false, source: "republish" });
      }
      if (selectionToRestore) {
        restoringSelection = true;
        const restore = cbRef.current.onSelectEnd
          ? { ...selectionToRestore, include_rows: true }
          : selectionToRestore;
        emitMessage(restore);
      }
      if (ghost && !ghost.selectionPending && !ghost.densityPending) settleGhostAfterDraw();
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
        if (restoringSelection) {
          restoringSelection = false;
        } else if (cbRef.current.onSelectEnd) {
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
      if (ghost) {
        if (message.type === "selection") ghost.selectionPending = false;
        if (message.type === "density_update") ghost.densityPending = false;
        if (!ghost.selectionPending && !ghost.densityPending) settleGhostAfterDraw();
      }
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
      settleGhost();
      if (tracksClickInput) el.removeEventListener("click", rememberClick, true);
      if (hoverTimer !== null) clearTimeout(hoverTimer);
      if (viewTimer !== null) clearTimeout(viewTimer);
      hoverTimer = null;
      viewTimer = null;
      pendingHover = null;
      pendingView = null;
      pendingClickInput = null;
      clickInputs.clear();
      restoringSelection = false;
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
  }, [token, src]);

  // One DOM node, two consumers: our mount logic and reflex's ref registry.
  const mergedRef = (node) => {
    elRef.current = node;
    if (typeof externalRef === "function") externalRef(node);
    else if (externalRef) externalRef.current = node;
  };
  return jsx("div", { ...divProps, ref: mergedRef });
}
