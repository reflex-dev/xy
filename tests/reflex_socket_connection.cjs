// Execute the shipped wrapper against real Socket.IO peers. Only React/DOM and
// the renderer are stubbed: this gate tests transport and render dispatch, not
// GPU pixels (covered by the browser smoke). Run via test_reflex_socket_connection.py.
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { createServer } = require("node:http");
const { resolve } = require("node:path");
const { setTimeout: delay } = require("node:timers/promises");
const { test } = require("node:test");
const { io } = require("socket.io-client");
const { Server } = require("socket.io");

const wrapper = readFileSync(resolve(__dirname, "../python/reflex_xy/assets/XYChart.jsx"), "utf8")
  .replace(/^import[\s\S]*?;\s*$/gm, "")
  .replace("export function XYChart", "function XYChart");

async function until(check, label) {
  const deadline = Date.now() + 3000;
  while (!check()) {
    assert.ok(Date.now() < deadline, `Timed out: ${label}`);
    await delay(10);
  }
}

function loadWrapper(endpoint) {
  let effects = [];
  const renders = [];
  const windows = {};
  class ChartView {
    constructor(el, spec, buffers) {
      this.spec = spec;
      this.buffers = buffers;
      renders.push(this);
    }
    destroy() { this.destroyed = true; }
  }
  // Refs attached during the latest render, detached before cleanup the way
  // React commits a deletion: DOM refs are cleared (callback refs called with
  // null, object refs nulled) before passive effect cleanups run.
  let attachedRefs = [];
  function jsx(tag, props, ...children) {
    const el = {
      id: props.id,
      clientWidth: 400,
      replaceChildren() {},
      addEventListener() {},
      removeEventListener() {},
    };
    if (typeof props.ref === "function") props.ref(el);
    else if (props.ref) props.ref.current = el;
    if (props.ref) attachedRefs.push(props.ref);
    return el;
  }
  const factory = new Function(
    "io", "env", "reflexEnvironment", "getBackendURL", "getToken",
    "useEffect", "useRef", "useState", "jsx", "ChartView", "window",
    `${wrapper}\nreturn {XYChart, xySocket, getSocket: () => sharedSocket};`,
  );
  const loaded = factory(
    io, { EVENT: endpoint, TRANSPORT: "websocket" }, { version: "test" },
    (url) => new URL(url), () => "session-token",
    (callback) => effects.push(callback), (current) => ({ current }),
    (value) => [value, () => {}], jsx, ChartView, windows,
  );
  return {
    ...loaded,
    renders,
    windows,
    mount(id, props = { figure: { token: "figure-token" } }) {
      effects = [];
      attachedRefs = [];
      const mountProps = id === undefined ? { ...props } : { id, ...props };
      // Reflex attaches its own object ref to id-bearing components.
      const externalRef = { current: null };
      if (id !== undefined) mountProps.ref = externalRef;
      loaded.XYChart(mountProps);
      const refs = attachedRefs;
      const cleanups = effects.map((effect) => effect()).filter(Boolean);
      return () => {
        refs.forEach((ref) => {
          if (typeof ref === "function") ref(null);
          else ref.current = null;
        });
        assert.equal(externalRef.current, null, "external object ref detached");
        cleanups.reverse().forEach((cleanup) => cleanup());
      };
    },
  };
}

for (const order of ["warm-manager", "open-warm-manager", "legacy-auto-connect", "open-legacy-manager", "xy-first"]) {
  test(`${order}: subscribe, dispatch payload, share transport, resubscribe`, async () => {
    const http = createServer();
    const server = new Server(http, { path: "/_event", transports: ["websocket"] });
    server.of("/_event");
    let connections = 0;
    let namespaceConnections = 0;
    server.engine.on("connection", () => connections++);
    const subs = [];
    const unsubs = [];
    server.of("/_xy").on("connection", (socket) => {
      namespaceConnections++;
      socket.on("sub", (request) => {
        subs.push(request);
        socket.emit("payload", {
          ...request, version: 1, spec: { traces: [] },
          buffers: [Buffer.from(new Float32Array([1, 2]).buffer)],
        });
      });
      socket.on("unsub", (request) => unsubs.push(request));
    });
    await new Promise((resolve) => http.listen(0, "127.0.0.1", resolve));
    const origin = `http://127.0.0.1:${http.address().port}`;
    const loaded = loadWrapper(`${origin}/_event`);
    let app;
    const mounts = [];
    const makeApp = () => io(`${origin}/_event`, {
      path: "/_event", transports: ["websocket"], protocols: ["test"],
      query: { token: "session-token" }, reconnection: false,
      autoConnect: order === "legacy-auto-connect" || order === "open-legacy-manager",
    });
    try {
      if (order !== "xy-first") {
        app = makeApp();
        if (order === "open-warm-manager" || order === "open-legacy-manager") {
          app.connect();
          await until(() => app.connected, "app namespace connected first");
        }
      }
      mounts.push(loaded.mount("one"));
      if (!app) app = makeApp();
      app.connect();
      await until(() => loaded.renders.length === 1 && app.connected, "live chart payload dispatched");
      const socket = loaded.getSocket();
      assert.equal(socket.io, app.io, "both namespaces must use the same manager");
      assert.equal(connections, 1, "one physical transport");
      assert.equal(namespaceConnections, 1, "one namespace CONNECT per transport");
      assert.deepEqual([...loaded.renders[0].buffers], [0, 0, 128, 63, 0, 0, 0, 64]);
      assert.equal(subs.length, 1);
      assert.equal(socket.io.reconnection(), false, "Reflex owns reconnects");
      assert.equal(socket.io._autoConnect, order === "legacy-auto-connect" || order === "open-legacy-manager" || order === "xy-first");

      // A second chart uses the cached namespace without another connection.
      mounts.push(loaded.mount("two"));
      await until(() => loaded.renders.length === 2, "second mount payload");
      assert.equal(connections, 1);
      assert.equal(subs.length, 2);
      assert.notEqual(subs[0].mid, subs[1].mid);

      // Simulate the app plane closing and reopening its shared manager.
      // A chart mounting during the pause must NOT reopen it on its own.
      app.io.disconnect();
      await until(() => !socket.connected && !app.connected, "manager closed");
      mounts.push(loaded.mount("during-pause"));
      await delay(30);
      assert.equal(app.io._readyState, "closed");
      assert.equal(connections, 1);
      app.connect();
      await until(() => loaded.renders.length === 5, "all mounts resubscribe after app reconnect");
      assert.equal(connections, 2);
      assert.equal(namespaceConnections, 2);
      assert.equal(subs.length, 5);
      assert.equal(socket.io, app.io);
      assert.deepEqual([...loaded.windows.__xy_views.keys()].sort(), ["during-pause", "one", "two"]);

      mounts.pop()();
      mounts.pop()();
      await delay(30);
      assert.equal(unsubs.length, 0, "same-token mounts retain the shared room");
      assert.deepEqual([...loaded.windows.__xy_views.keys()], ["one"],
        "unmounted views leave the registry even after React cleared the DOM ref");
      mounts.pop()();
      await until(() => unsubs.length === 1, "last mount unsubscribes");
      assert.equal(loaded.windows.__xy_views.size, 0, "last unmount empties the view registry");
      assert.equal(app.connected, true, "chart cleanup leaves the app transport alive");
      assert.equal(socket.connected, true);
    } finally {
      mounts.reverse().forEach((cleanup) => cleanup());
      loaded.getSocket()?.disconnect();
      app?.disconnect();
      await new Promise((resolve) => server.close(resolve));
    }
  });
}

test("anonymous mounts register and release their view by mount id", async () => {
  const http = createServer();
  const server = new Server(http, { path: "/_event", transports: ["websocket"] });
  server.of("/_event");
  server.of("/_xy").on("connection", (socket) => {
    socket.on("sub", (request) => socket.emit("payload", {
      ...request, version: 1, spec: { traces: [] },
      buffers: [Buffer.from(new Float32Array([1]).buffer)],
    }));
  });
  await new Promise((resolve) => http.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${http.address().port}`;
  const loaded = loadWrapper(`${origin}/_event`);
  const app = io(`${origin}/_event`, {
    path: "/_event", transports: ["websocket"], protocols: ["test"],
    query: { token: "session-token" }, reconnection: false, autoConnect: false,
  });
  const mounts = [];
  try {
    mounts.push(loaded.mount(undefined), loaded.mount("named"));
    app.connect();
    await until(() => loaded.renders.length === 2, "both mounts rendered");
    const keys = [...loaded.windows.__xy_views.keys()];
    assert.equal(keys.length, 2);
    assert.ok(keys.includes("named"));
    assert.match(keys.find((key) => key !== "named"), /^m\d+$/);
    mounts.shift()();
    assert.deepEqual([...loaded.windows.__xy_views.keys()], ["named"]);
    mounts.shift()();
    assert.equal(loaded.windows.__xy_views.size, 0);
    assert.ok(loaded.renders.every((view) => view.destroyed), "every view destroyed");
    assert.equal(app.connected, true, "chart cleanup leaves the app transport alive");
  } finally {
    mounts.forEach((cleanup) => cleanup());
    loaded.getSocket()?.disconnect();
    app.disconnect();
    await new Promise((resolve) => server.close(resolve));
  }
});

test("an unhydrated figure never creates a socket", () => {
  const loaded = loadWrapper("http://127.0.0.1:1/_event");
  const unmount = loaded.mount("empty", { figure: { token: "" } });
  assert.equal(loaded.getSocket(), null);
  unmount();
});
