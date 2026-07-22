#!/usr/bin/env node
/** Bounded, data-driven pan/zoom acceptance matrix (TST-NI-011).
 *
 * Profiles:
 *   full     - every standalone case in Chromium (the hard CI gate)
 *   focused  - drag/wheel/box subset in Chromium, Firefox, and WebKit
 *   reflex   - live and static charts in the real Reflex example
 *
 * Every run writes machine-readable evidence, including on failure.  The
 * catalog and evidence validators intentionally run without a browser so the
 * matrix wiring remains cheap to test and difficult to silently narrow.
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const BUNDLE = join(ROOT, "python", "xy", "static", "standalone.js");
const protocolSource = readFileSync(join(ROOT, "python", "xy", "config.py"), "utf8");
const protocolMatch = protocolSource.match(/^PROTOCOL_VERSION\s*=\s*(\d+)\s*$/m);
if (!protocolMatch) throw new Error("could not read PROTOCOL_VERSION from python/xy/config.py");
const PROTOCOL_VERSION = Number(protocolMatch[1]);

const ENGINE_NAMES = ["chromium", "firefox", "webkit"];
let engines = null;

async function browserEngines() {
  if (engines === null) {
    try {
      engines = await import("playwright");
    } catch (error) {
      fail(`Playwright is required for browser profiles; run npm ci\n${error}`);
    }
  }
  return engines;
}
const REQUIRED = Object.freeze({
  actions: ["drag", "wheel", "box", "toolbar_zoom", "reset"],
  axis_classes: ["linear", "log", "reversed", "category", "dual", "named"],
  hosts: ["standalone", "reflex-live", "reflex-static"],
  invariants: [
    "participating_ranges_change",
    "nonparticipating_ranges_exact",
    "bounds",
    "zoom_limits",
    "event_source_axes_phase",
    "linked_axes_no_echo",
    "reduced_motion",
    "no_op_no_event_or_lod",
    "semantic_layout_health",
    "json_safe_reflex_payload",
  ],
});

const CASES = Object.freeze([
  {
    id: "linear-drag-bounds",
    profiles: ["full", "focused"],
    actions: ["drag"],
    axis_classes: ["linear"],
    hosts: ["standalone"],
  },
  {
    id: "log-wheel-link-limits",
    profiles: ["full", "focused"],
    actions: ["wheel"],
    axis_classes: ["log"],
    hosts: ["standalone"],
  },
  {
    id: "reversed-box-reduced-motion",
    profiles: ["full", "focused"],
    actions: ["box"],
    axis_classes: ["reversed"],
    hosts: ["standalone"],
  },
  {
    id: "category-toolbar-default-limit",
    profiles: ["full"],
    actions: ["toolbar_zoom", "reset"],
    axis_classes: ["category"],
    hosts: ["standalone"],
  },
  {
    id: "dual-named-partial-limits",
    profiles: ["full"],
    actions: ["toolbar_zoom", "reset"],
    axis_classes: ["dual", "named"],
    hosts: ["standalone"],
  },
]);

const REFLEX_CASES = Object.freeze([
  {
    id: "reflex-live-wheel",
    profiles: ["reflex"],
    actions: ["wheel"],
    axis_classes: ["linear"],
    hosts: ["reflex-live"],
  },
  {
    id: "reflex-static-toolbar-reset",
    profiles: ["reflex"],
    actions: ["toolbar_zoom", "reset"],
    axis_classes: ["linear"],
    hosts: ["reflex-static"],
  },
]);

function unique(values) {
  return [...new Set(values)];
}

function sorted(values) {
  return [...values].sort();
}

function equalSet(actual, expected) {
  return JSON.stringify(sorted(unique(actual))) === JSON.stringify(sorted(unique(expected)));
}

function fail(message) {
  throw new Error(message);
}

function check(condition, message) {
  if (!condition) fail(message);
}

function catalog() {
  return {
    schema_version: 1,
    requirement: "TST-NI-011",
    required: REQUIRED,
    cases: [...CASES, ...REFLEX_CASES],
    profiles: {
      full: {
        browsers: ["chromium"],
        cases: CASES.filter((item) => item.profiles.includes("full")).map((item) => item.id),
      },
      focused: {
        browsers: ["chromium", "firefox", "webkit"],
        cases: CASES.filter((item) => item.profiles.includes("focused")).map((item) => item.id),
      },
      reflex: {
        browsers: ["chromium"],
        cases: REFLEX_CASES.map((item) => item.id),
      },
    },
  };
}

export function validateCatalog(value = catalog()) {
  check(value?.schema_version === 1, "catalog schema_version must be 1");
  check(value?.requirement === "TST-NI-011", "catalog requirement must be TST-NI-011");
  const cases = value.cases || [];
  check(cases.length === 7, `catalog must contain 7 bounded cases, got ${cases.length}`);
  check(new Set(cases.map((item) => item.id)).size === cases.length, "catalog case IDs must be unique");
  for (const field of ["actions", "axis_classes", "hosts"]) {
    const actual = cases.flatMap((item) => item[field] || []);
    check(equalSet(actual, REQUIRED[field]), `catalog ${field} coverage is incomplete`);
  }
  check(
    equalSet(value.profiles?.focused?.browsers || [], ["chromium", "firefox", "webkit"]),
    "focused profile must hard-run Chromium, Firefox, and WebKit",
  );
  check((value.profiles?.full?.cases || []).length === 5, "full profile must contain 5 cases");
  check((value.profiles?.focused?.cases || []).length === 3, "focused profile must contain 3 cases");
  check((value.profiles?.reflex?.cases || []).length === 2, "reflex profile must contain 2 cases");
  return true;
}

function coverageFor(profile) {
  const selected = [...CASES, ...REFLEX_CASES].filter((item) => item.profiles.includes(profile));
  return {
    actions: sorted(unique(selected.flatMap((item) => item.actions))),
    axis_classes: sorted(unique(selected.flatMap((item) => item.axis_classes))),
    hosts: sorted(unique(selected.flatMap((item) => item.hosts))),
  };
}

export function validateEvidence(value) {
  validateCatalog(value?.catalog);
  check(value?.schema_version === 1, "evidence schema_version must be 1");
  check(["full", "focused", "reflex"].includes(value?.profile), "unknown evidence profile");
  check(value?.status === "passed", `evidence status is ${value?.status || "missing"}, expected passed`);
  const expectedCoverage = coverageFor(value.profile);
  for (const field of ["actions", "axis_classes", "hosts"]) {
    check(equalSet(value.coverage?.[field] || [], expectedCoverage[field]), `${field} evidence coverage is incomplete`);
  }
  const expectedBrowsers = value.catalog.profiles[value.profile].browsers;
  check(equalSet(Object.keys(value.browsers || {}), expectedBrowsers), "evidence browser coverage is incomplete");
  const expectedCases = value.catalog.profiles[value.profile].cases;
  for (const browserName of expectedBrowsers) {
    const browser = value.browsers[browserName];
    check(browser?.status === "passed", `${browserName} evidence did not pass`);
    check(equalSet((browser.cases || []).map((item) => item.id), expectedCases), `${browserName} case coverage is incomplete`);
    for (const item of browser.cases || []) {
      check(item.status === "passed", `${browserName}/${item.id} did not pass`);
      check((item.assertions?.semantic || []).length > 0, `${browserName}/${item.id} lacks semantic evidence`);
      check((item.assertions?.layout || []).length > 0, `${browserName}/${item.id} lacks layout evidence`);
    }
  }
  return true;
}

function parseArgs(argv) {
  const args = {
    profile: "full",
    browsers: null,
    evidence: "pan-zoom-matrix-evidence.json",
    executablePath: null,
    url: null,
    catalogOnly: false,
    verifyEvidence: null,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--catalog") args.catalogOnly = true;
    else if (arg === "--profile") args.profile = argv[++i];
    else if (arg.startsWith("--profile=")) args.profile = arg.split("=", 2)[1];
    else if (arg === "--browsers") args.browsers = argv[++i];
    else if (arg.startsWith("--browsers=")) args.browsers = arg.split("=", 2)[1];
    else if (arg === "--evidence") args.evidence = argv[++i];
    else if (arg === "--executable-path") args.executablePath = argv[++i];
    else if (arg === "--url") args.url = argv[++i];
    else if (arg === "--verify-evidence") args.verifyEvidence = argv[++i];
    else fail(`unknown argument: ${arg}`);
  }
  check(["full", "focused", "reflex"].includes(args.profile), `unknown profile ${args.profile}`);
  return args;
}

function writeEvidence(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function makeSpec(kind) {
  let axes;
  let interaction;
  if (kind === "linear-drag-bounds") {
    axes = {
      x: { kind: "linear", label: "bounded x", range: [0, 10], bounds: [-5, 15] },
      y: { kind: "linear", label: "fixed y", range: [-5, 5], bounds: [-10, 10] },
    };
    interaction = {
      navigation: true, pan: true, zoom: true, default_drag_action: "pan",
      pan_axes: ["x"], zoom_axes: ["x"], reset_axes: ["x"],
    };
  } else if (kind === "log-wheel-link-limits") {
    axes = {
      x: { kind: "linear", scale: "log", label: "log x", range: [1, 1000], bounds: [0.1, 10000] },
      y: { kind: "linear", label: "fixed y", range: [0, 10], bounds: [-10, 20] },
    };
    interaction = {
      navigation: true, pan: true, zoom: true, wheel_zoom: true,
      pan_axes: ["x"], zoom_axes: ["x"], reset_axes: ["x"],
      zoom_limits: { x: [1, 4] }, link_group: "tst-ni-011-log", link_axes: ["x"],
    };
  } else if (kind === "reversed-box-reduced-motion") {
    axes = {
      x: { kind: "linear", label: "reversed x", range: [10, 0], bounds: [0, 10] },
      y: { kind: "linear", label: "y", range: [0, 10], bounds: [0, 10] },
    };
    interaction = {
      navigation: true, pan: true, zoom: true, box_zoom: true,
      default_drag_action: "zoom", zoom_axes: ["x", "y"], reset_axes: ["x", "y"],
      zoom_limits: { x: [1, 8], y: [1, 8] },
    };
  } else if (kind === "category-toolbar-default-limit") {
    axes = {
      x: {
        kind: "category", label: "category x", range: [-0.5, 5.5], bounds: [-0.5, 5.5],
        categories: ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"],
      },
      y: { kind: "linear", label: "fixed y", range: [0, 10], bounds: [-10, 20] },
    };
    interaction = {
      navigation: true, pan: true, zoom: true, zoom_axes: ["x"], reset_axes: ["x"],
    };
  } else if (kind === "dual-named-partial-limits") {
    axes = {
      x: { kind: "linear", label: "named x", range: [0, 10], bounds: [-10, 20] },
      y: { kind: "linear", label: "primary y", range: [-1, 1], bounds: [-2, 2] },
      y2: { kind: "linear", label: "secondary y", range: [-50, 50], bounds: [-200, 200], side: "right" },
    };
    interaction = {
      navigation: true, pan: true, zoom: true,
      pan_axes: ["x", "y2"], zoom_axes: ["x", "y2"], reset_axes: ["x", "y2"],
      // x intentionally inherits the default (1, None); y2 exercises both
      // finite sides and the one-axis-hits-a-limit multi-axis case.
      zoom_limits: { y2: [0.5, 2] },
    };
  } else {
    fail(`unknown matrix case ${kind}`);
  }

  const columns = [];
  const values = [];
  const ship = (items) => {
    const index = columns.length;
    columns.push({ byte_offset: values.length * 4, len: items.length, offset: 0, scale: 1, kind: "float" });
    values.push(...items);
    return index;
  };
  const xValues = axes.x.scale === "log"
    ? [1, 3, 10, 30, 100, 300, 1000]
    : axes.x.kind === "category" ? [0, 1, 2, 3, 4, 5] : [0, 1.5, 3, 5, 7, 8.5, 10];
  const yValues = xValues.map((_, index) => axes.y.range[0]
    + (axes.y.range[1] - axes.y.range[0]) * ((index + 1) / (xValues.length + 1)));
  const traces = [{
    id: 0, kind: "scatter", name: "primary", tier: "direct", n_points: xValues.length,
    style: { opacity: 0.9 }, color: { mode: "constant", color: "#2563eb" },
    size: { mode: "constant", size: 11 }, x: ship(xValues), y: ship(yValues),
  }];
  if (axes.y2) {
    const y2Values = xValues.map((_, index) => -40 + 80 * ((index + 1) / (xValues.length + 1)));
    traces.push({
      id: 1, kind: "scatter", name: "secondary", tier: "direct", n_points: xValues.length,
      x_axis: "x", y_axis: "y2", style: { opacity: 0.9 },
      color: { mode: "constant", color: "#dc2626" }, size: { mode: "constant", size: 10 },
      x: ship(xValues), y: ship(y2Values),
    });
  }
  return {
    spec: {
      protocol: PROTOCOL_VERSION, width: 680, height: 390, title: `Pan/zoom ${kind}`,
      show_legend: false, axes, x_axis: axes.x, y_axis: axes.y,
      traces, columns, interaction, backend: "none",
    },
    values,
  };
}

async function mountStandalone(page, caseId, peers = 1) {
  const { spec, values } = makeSpec(caseId);
  const mounts = Array.from({ length: peers }, (_, index) => ({ id: index === 0 ? "a" : "b" }));
  await page.setContent(`<!doctype html><meta charset=utf-8><style>body{margin:8px;display:grid;gap:8px}.mount{width:680px;height:390px}</style>${mounts.map((item) => `<div class=mount id=${item.id}></div>`).join("")}`);
  await page.addScriptTag({ path: BUNDLE });
  await page.evaluate(({ spec, values, mounts }) => {
    const originalGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, attributes) {
      if (type === "webgl2") {
        return originalGetContext.call(this, type, { ...attributes, preserveDrawingBuffer: true });
      }
      return originalGetContext.call(this, type, attributes);
    };
    window.xyMatrix = { views: {}, events: {}, lod: {}, initial: {} };
    for (const mount of mounts) {
      const view = window.xy.renderStandalone(
        document.getElementById(mount.id), structuredClone(spec), new Float32Array(values).buffer,
      );
      window.xyMatrix.views[mount.id] = view;
      window.xyMatrix.events[mount.id] = [];
      window.xyMatrix.lod[mount.id] = 0;
      window.xyMatrix.initial[mount.id] = {
        ranges: Object.fromEntries(view._axisIds().map((id) => [id, [...view._axisRange(id)]])),
      };
      view.root.addEventListener("xy:view_change", (event) => {
        window.xyMatrix.events[mount.id].push(JSON.parse(JSON.stringify(event.detail)));
      });
      const schedule = view._scheduleViewRequest.bind(view);
      view._scheduleViewRequest = (...args) => {
        window.xyMatrix.lod[mount.id] += 1;
        return schedule(...args);
      };
      view._drawNow();
    }
    HTMLCanvasElement.prototype.getContext = originalGetContext;
  }, { spec, values, mounts });
  await page.waitForTimeout(60);
}

async function snapshot(page, id = "a") {
  return page.evaluate((id) => {
    const view = window.xyMatrix.views[id];
    view._drawNow();
    const root = view.root.getBoundingClientRect();
    const canvas = view.canvas.getBoundingClientRect();
    const gl = view.gl;
    const pixels = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
    gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    let lit = 0;
    for (let index = 0; index < pixels.length; index += 4) {
      if (pixels[index] + pixels[index + 1] + pixels[index + 2] > 20) lit += 1;
    }
    const labels = [...view.labels.querySelectorAll('[data-xy-slot="tick_label"], [data-xy-slot="axis_title"]')];
    return {
      ranges: Object.fromEntries(view._axisIds().map((axisId) => [axisId, [...view._axisRange(axisId)]])),
      home: Object.fromEntries(view._axisIds().map((axisId) => [axisId, [...view._axisRange(axisId, view.view0)]])),
      bounds: Object.fromEntries(view._axisIds().map((axisId) => [axisId, view._axis(axisId).bounds || null])),
      scales: Object.fromEntries(view._axisIds().map((axisId) => [axisId, view._axis(axisId).scale || "linear"])),
      events: structuredClone(window.xyMatrix.events[id]),
      lod: window.xyMatrix.lod[id],
      dragMode: view.dragMode,
      reducedMotion: view._prefersReducedMotion(),
      animationActive: view._viewAnim !== null,
      layout: {
        root: { x: root.x, y: root.y, width: root.width, height: root.height },
        canvas: { x: canvas.x, y: canvas.y, width: canvas.width, height: canvas.height },
        labels: labels.map((label) => {
          const rect = label.getBoundingClientRect();
          return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, text: label.textContent };
        }),
      },
      lit,
      zoomLabel: view._zoomMenuLabel?.dataset.xyZoomExact || view._zoomMenuLabel?.textContent || null,
    };
  }, id);
}

function exact(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function near(a, b, tolerance = 1e-8) {
  return Math.abs(a - b) <= tolerance * Math.max(1, Math.abs(a), Math.abs(b));
}

function coord(value, scale) {
  return scale === "log" ? Math.log10(value) : value;
}

function span(range, scale = "linear") {
  return Math.abs(coord(range[1], scale) - coord(range[0], scale));
}

function magnification(state, axisId) {
  return span(state.home[axisId], state.scales[axisId]) / span(state.ranges[axisId], state.scales[axisId]);
}

function assertBounds(state) {
  for (const [axisId, bounds] of Object.entries(state.bounds)) {
    if (!bounds) continue;
    const range = state.ranges[axisId];
    check(Math.min(...range) >= Math.min(...bounds) - 1e-8, `${axisId} range escaped lower bound`);
    check(Math.max(...range) <= Math.max(...bounds) + 1e-8, `${axisId} range escaped upper bound`);
  }
}

function assertLayout(before, after) {
  check(after.lit > 40, `rendered only ${after.lit} lit WebGL pixels`);
  check(after.layout.canvas.width > 100 && after.layout.canvas.height > 100, "canvas has invalid layout");
  check(after.layout.labels.length >= 2, "axis labels are missing");
  check(after.layout.labels.every((item) => [item.x, item.y, item.width, item.height].every(Number.isFinite)), "axis label layout is non-finite");
  check(near(before.layout.root.width, after.layout.root.width, 1e-4), "root width changed during navigation");
  check(near(before.layout.root.height, after.layout.root.height, 1e-4), "root height changed during navigation");
}

function lastEvent(state, source) {
  const events = state.events.filter((event) => event.source === source);
  check(events.length > 0, `missing ${source} event`);
  return events.at(-1);
}

function assertEvent(state, source, axes, phase = "end") {
  const event = lastEvent(state, source);
  check(event.phase === phase, `${source} final phase was ${event.phase}, expected ${phase}`);
  check(equalSet(event.axes || [], axes), `${source} axes were ${JSON.stringify(event.axes)}, expected ${JSON.stringify(axes)}`);
  check(Number.isInteger(event.interaction_id), `${source} lacks an interaction_id`);
  check(JSON.stringify(event).length > 0, `${source} payload is not JSON safe`);
  return event;
}

async function drag(page, id, from, to) {
  const rect = await page.locator(`#${id} [data-xy-slot="canvas"]`).boundingBox();
  check(rect, `missing ${id} canvas`);
  const point = (fraction) => ({ x: rect.x + rect.width * fraction[0], y: rect.y + rect.height * fraction[1] });
  const a = point(from), b = point(to);
  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  await page.mouse.move(b.x, b.y, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(230);
}

async function wheel(page, id, deltaY) {
  const rect = await page.locator(`#${id} [data-xy-slot="canvas"]`).boundingBox();
  check(rect, `missing ${id} canvas`);
  await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2);
  await page.mouse.wheel(0, deltaY);
  await page.waitForTimeout(230);
}

async function toolbar(page, id, action) {
  const root = page.locator(`#${id}`);
  await root.locator('[data-xy-modebar-menu-trigger]').click();
  await root.locator(`[data-xy-modebar-menu-item="${action}"]`).click();
  await page.waitForTimeout(230);
}

const CASE_ASSERTIONS = {
  "linear-drag-bounds": {
    semantic: ["real pointer drag", "x changed", "y exact", "bounds", "pan_drag end"],
    layout: ["nonblank WebGL", "finite labels", "stable chart box"],
  },
  "log-wheel-link-limits": {
    semantic: ["real wheel", "log magnification limit", "linked x only", "no echo", "no-op event/LOD"],
    layout: ["nonblank WebGL", "finite labels", "stable chart box"],
  },
  "reversed-box-reduced-motion": {
    semantic: ["real box drag", "reversal preserved", "both axes changed", "reduced motion"],
    layout: ["nonblank WebGL", "finite labels", "stable chart box"],
  },
  "category-toolbar-default-limit": {
    semantic: ["toolbar zoom in/out", "default zoom-out no-op", "category range", "toolbar reset"],
    layout: ["category labels", "nonblank WebGL", "stable chart box"],
  },
  "dual-named-partial-limits": {
    semantic: ["dual named axes", "partial limit map", "one-axis clamp", "finite zoom-out", "reset subset"],
    layout: ["secondary-axis labels", "nonblank WebGL", "stable chart box"],
  },
};

async function runStandaloneCase(page, caseId) {
  const peers = caseId === "log-wheel-link-limits" ? 2 : 1;
  await mountStandalone(page, caseId, peers);
  const before = await snapshot(page);

  if (caseId === "linear-drag-bounds") {
    await drag(page, "a", [0.5, 0.5], [0.72, 0.5]);
    const after = await snapshot(page);
    check(!exact(after.ranges.x, before.ranges.x), "drag did not change x");
    check(exact(after.ranges.y, before.ranges.y), "drag changed nonparticipating y");
    assertBounds(after);
    assertEvent(after, "pan_drag", ["x"]);
    const gestureEvents = after.events.filter((event) => event.source === "pan_drag");
    check(gestureEvents.at(-1).phase === "end", "drag lacks a final end event");
    check(new Set(gestureEvents.map((event) => event.interaction_id)).size === 1, "drag event IDs were not coalesced");
    assertLayout(before, after);
    return after;
  }

  if (caseId === "log-wheel-link-limits") {
    await wheel(page, "a", -3000);
    const after = await snapshot(page);
    const peer = await snapshot(page, "b");
    check(near(magnification(after, "x"), 4, 1e-6), `log x magnification was ${magnification(after, "x")}, expected 4`);
    check(exact(after.ranges.y, before.ranges.y), "wheel changed nonparticipating y");
    check(exact(peer.ranges.x, after.ranges.x), "linked peer did not receive x");
    check(exact(peer.ranges.y, before.ranges.y), "linked peer changed y");
    assertEvent(after, "wheel_zoom", ["x"]);
    assertEvent(peer, "linked", ["x"]);
    check(!after.events.some((event) => event.source === "linked"), "linked peer echoed to origin");
    const wheelEvents = after.events.filter((event) => event.source === "wheel_zoom");
    check(wheelEvents.some((event) => event.phase === "update"), "wheel lacks an update event");
    check(wheelEvents.at(-1).phase === "end", "wheel lacks a final end event");
    check(new Set(wheelEvents.map((event) => event.interaction_id)).size === 1, "wheel event IDs were not coalesced");
    const eventCount = after.events.length;
    const lodCount = after.lod;
    await wheel(page, "a", -1000);
    const noop = await snapshot(page);
    check(exact(noop.ranges, after.ranges), "clamped wheel no-op changed ranges");
    check(noop.events.length === eventCount, "clamped wheel no-op emitted a view event");
    check(noop.lod === lodCount, "clamped wheel no-op scheduled LOD work");
    assertBounds(noop);
    assertLayout(before, noop);
    return noop;
  }

  if (caseId === "reversed-box-reduced-motion") {
    check(before.dragMode === "zoom", `default box mode resolved to ${before.dragMode}`);
    await drag(page, "a", [0.2, 0.2], [0.72, 0.75]);
    const after = await snapshot(page);
    check(span(after.ranges.x) < span(before.ranges.x), "box did not narrow reversed x");
    check(span(after.ranges.y) < span(before.ranges.y), "box did not narrow y");
    check(after.ranges.x[0] > after.ranges.x[1], "box lost x reversal");
    check(after.reducedMotion && !after.animationActive, "reduced motion did not suppress animation");
    assertEvent(after, "box_zoom", ["x", "y"]);
    assertBounds(after);
    assertLayout(before, after);
    return after;
  }

  if (caseId === "category-toolbar-default-limit") {
    const noOpEvents = before.events.length;
    const noOpLod = before.lod;
    await toolbar(page, "a", "zoomout");
    let current = await snapshot(page);
    check(exact(current.ranges, before.ranges), "default zoom-out limit did not clamp at home");
    check(current.events.length === noOpEvents, "default-limit no-op emitted a view event");
    check(current.lod === noOpLod, "default-limit no-op scheduled LOD work");
    await toolbar(page, "a", "zoomin");
    current = await snapshot(page);
    check(near(magnification(current, "x"), 2), "category toolbar zoom-in did not reach 2x");
    check(exact(current.ranges.y, before.ranges.y), "category zoom changed y");
    assertEvent(current, "zoom_in", ["x"]);
    await toolbar(page, "a", "zoomout");
    current = await snapshot(page);
    check(exact(current.ranges.x, before.ranges.x), "category zoom-out did not return home");
    assertEvent(current, "zoom_out", ["x"]);
    await toolbar(page, "a", "zoomin");
    await toolbar(page, "a", "reset");
    current = await snapshot(page);
    check(exact(current.ranges.x, before.ranges.x), "category reset did not restore x");
    check(exact(current.ranges.y, before.ranges.y), "category reset changed y");
    assertEvent(current, "reset", ["x"]);
    check(current.layout.labels.some((item) => item.text === "alpha" || item.text === "zeta"), "category labels disappeared");
    assertBounds(current);
    assertLayout(before, current);
    return current;
  }

  if (caseId === "dual-named-partial-limits") {
    await toolbar(page, "a", "zoomin");
    await toolbar(page, "a", "zoomin");
    let current = await snapshot(page);
    check(near(magnification(current, "x"), 4), "named x did not inherit unbounded zoom-in default");
    check(near(magnification(current, "y2"), 2), "named y2 did not clamp at 2x");
    check(exact(current.ranges.y, before.ranges.y), "dual-axis zoom changed primary y");
    const secondZoom = current.events.filter((event) => event.source === "zoom_in").at(-1);
    check(equalSet(secondZoom.axes, ["x"]), "one-axis-at-limit event did not report only x");
    await toolbar(page, "a", "reset");
    current = await snapshot(page);
    check(exact(current.ranges, before.ranges), "dual reset did not restore selected axes");
    assertEvent(current, "reset", ["x", "y2"]);
    // Seed an over-wide candidate through the shared clamping path.  Toolbar
    // zoom-out is home-capped before that path, so this setup is the only way
    // to exercise a configured minimum below 1 without weakening the claim
    // that the user-facing command itself was driven through the real menu.
    await page.evaluate(() => {
      const view = window.xyMatrix.views.a;
      const ranges = Object.fromEntries(view._axisIds().map((axisId) => [axisId, [...view._axisRange(axisId)]]));
      ranges.y2 = [-500, 500];
      view._setView({ ranges }, { animate: false, source: "programmatic", phase: "end" });
    });
    await page.waitForTimeout(100);
    current = await snapshot(page);
    check(near(magnification(current, "y2"), 0.5), "y2 finite zoom-out limit was not applied");
    check(exact(current.ranges.x, before.ranges.x), "partial-map x escaped its default home limit");
    check(exact(current.ranges.y, before.ranges.y), "finite zoom-out changed primary y");
    await toolbar(page, "a", "reset");
    current = await snapshot(page);
    check(exact(current.ranges, before.ranges), "dual reset after zoom-out did not restore home");
    check(current.layout.labels.some((item) => item.text === "secondary y"), "named secondary-axis label disappeared");
    assertBounds(current);
    assertLayout(before, current);
    return current;
  }

  fail(`case implementation missing: ${caseId}`);
}

async function launchEngine(name, executablePath = null) {
  const available = await browserEngines();
  const options = {
    headless: process.env.XY_PAN_ZOOM_HEADFUL !== "1" && process.env.XY_CONFORMANCE_HEADFUL !== "1",
  };
  if (name === "chromium" && executablePath) options.executablePath = executablePath;
  if (name === "firefox") {
    options.firefoxUserPrefs = { "webgl.disabled": false, "webgl.force-enabled": true };
  }
  try {
    return await available[name].launch(options);
  } catch (error) {
    fail(`${name} could not launch; install the selected Playwright engines\n${error}`);
  }
}

async function runStandaloneBrowser(name, profile, executablePath) {
  const browserResult = { status: "running", version: null, cases: [] };
  let browser;
  try {
    browser = await launchEngine(name, executablePath);
    browserResult.version = browser.version();
    const context = await browser.newContext({
      viewport: { width: 1460, height: 900 }, deviceScaleFactor: 1, reducedMotion: "reduce",
    });
    const selected = CASES.filter((item) => item.profiles.includes(profile));
    for (const item of selected) {
      const row = {
        id: item.id, status: "running", actions: item.actions,
        axis_classes: item.axis_classes, hosts: item.hosts,
        assertions: CASE_ASSERTIONS[item.id],
      };
      browserResult.cases.push(row);
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(String(error)));
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(message.text());
      });
      try {
        const hasWebGl2 = await page.evaluate(() => Boolean(document.createElement("canvas").getContext("webgl2")));
        check(hasWebGl2, `${name}: WebGL2 unavailable`);
        const final = await runStandaloneCase(page, item.id);
        check(errors.length === 0, `${name}/${item.id} page errors: ${errors.join("; ")}`);
        row.status = "passed";
        row.metrics = { event_count: final.events.length, lod_request_count: final.lod, lit_pixels: final.lit };
      } catch (error) {
        row.status = "failed";
        row.error = String(error?.stack || error);
      } finally {
        await page.close();
      }
    }
    await context.close();
    browserResult.status = browserResult.cases.every((item) => item.status === "passed") ? "passed" : "failed";
  } catch (error) {
    browserResult.status = "failed";
    browserResult.error = String(error?.stack || error);
  } finally {
    await browser?.close();
  }
  return browserResult;
}

async function instrumentReflex(page) {
  await page.waitForFunction(() => window.__xy_views?.has("overview") && window.__xy_views?.has("inline"), null, { timeout: 120_000 });
  await page.evaluate(() => {
    window.xyReflexMatrix = {};
    for (const id of ["overview", "inline"]) {
      const view = window.__xy_views.get(id);
      const record = {
        events: [], sends: [], home: Object.fromEntries(view._axisIds().map((axisId) => [axisId, [...view._axisRange(axisId)]])),
      };
      view.root.addEventListener("xy:view_change", (event) => record.events.push(JSON.parse(JSON.stringify(event.detail))));
      if (view.comm) {
        const send = view.comm.send.bind(view.comm);
        view.comm.send = (message) => {
          record.sends.push(JSON.parse(JSON.stringify(message)));
          return send(message);
        };
      }
      window.xyReflexMatrix[id] = record;
    }
  });
}

async function reflexState(page, id) {
  return page.evaluate((id) => {
    const view = window.__xy_views.get(id);
    const record = window.xyReflexMatrix[id];
    const root = view.root.getBoundingClientRect();
    const canvas = view.canvas.getBoundingClientRect();
    return {
      comm: view.comm !== null,
      transportViewChange: view.comm?.wantsViewChange?.() === true
        || view.interaction?.view_change === true
        || view.interaction?._transport_view_change === true,
      ranges: Object.fromEntries(view._axisIds().map((axisId) => [axisId, [...view._axisRange(axisId)]])),
      home: structuredClone(record.home),
      events: structuredClone(record.events), sends: structuredClone(record.sends),
      layout: { root: { width: root.width, height: root.height }, canvas: { width: canvas.width, height: canvas.height } },
      jsonSafe: (() => { try { JSON.stringify(record.events); JSON.stringify(record.sends); return true; } catch (_) { return false; } })(),
    };
  }, id);
}

async function reflexWheel(page, id, deltaY) {
  await page.locator(`#${id}`).scrollIntoViewIfNeeded();
  const box = await page.locator(`#${id} [data-xy-slot="canvas"]`).boundingBox();
  check(box, `missing Reflex ${id} canvas`);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, deltaY);
  await page.waitForTimeout(500);
}

async function reflexToolbar(page, id, action) {
  await page.locator(`#${id}`).scrollIntoViewIfNeeded();
  await page.locator(`#${id} [data-xy-modebar-menu-trigger]`).click();
  await page.locator(`#${id} [data-xy-modebar-menu-item="${action}"]`).click();
  await page.waitForTimeout(300);
}

async function runReflexBrowser(name, url, executablePath) {
  const result = { status: "running", version: null, cases: [] };
  let browser;
  try {
    browser = await launchEngine(name, executablePath);
    result.version = browser.version();
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
    const page = await context.newPage();
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(String(error)));
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 120_000 });
    await instrumentReflex(page);

    const liveRow = {
      id: "reflex-live-wheel", status: "running", actions: ["wheel"], axis_classes: ["linear"],
      hosts: ["reflex-live"], assertions: {
        semantic: ["real wheel", "live comm", "view_change end", "LOD request", "JSON-safe buffer-free state", "backend-derived detail"],
        layout: ["mounted live canvas", "stable chart box"],
      },
    };
    result.cases.push(liveRow);
    try {
      const before = await reflexState(page, "overview");
      check(before.comm && before.transportViewChange, "overview is not a subscribed live Reflex chart");
      await reflexWheel(page, "overview", -900);
      const after = await reflexState(page, "overview");
      check(!exact(after.ranges.x, before.ranges.x), "live Reflex wheel did not change x");
      check(exact(after.ranges.y, before.ranges.y), "live Reflex wheel changed nonparticipating y");
      assertEvent(after, "wheel_zoom", ["x"]);
      const transportedViews = after.sends.filter((message) => message.type === "view_change");
      check(transportedViews.some((message) => message.phase === "end"), "live Reflex did not transport final view_change");
      check(
        transportedViews.every((message) => !Object.keys(message).some((key) => /buffer|binary/i.test(key))),
        "live Reflex view state contained binary buffers",
      );
      check(after.sends.some((message) => message.type === "density_view"), "live Reflex did not request density LOD");
      check(after.jsonSafe, "live Reflex event payload was not JSON safe");
      await page.waitForFunction(
        () => /x ∈ \[[^\]]+\] · [\d,]+ points/.test(document.body.innerText),
        null,
        { timeout: 30_000 },
      );
      check(near(before.layout.root.width, after.layout.root.width, 1e-4), "live Reflex layout width changed");
      check(after.layout.canvas.width > 100 && after.layout.canvas.height > 100, "live Reflex canvas is not laid out");
      liveRow.status = "passed";
      liveRow.metrics = { event_count: after.events.length, transport_messages: after.sends.map((item) => item.type) };
    } catch (error) {
      liveRow.status = "failed";
      liveRow.error = String(error?.stack || error);
    }

    const staticRow = {
      id: "reflex-static-toolbar-reset", status: "running", actions: ["toolbar_zoom", "reset"],
      axis_classes: ["linear"], hosts: ["reflex-static"], assertions: {
        semantic: ["kernel-less static mount", "toolbar zoom", "local event", "reset home", "no transport"],
        layout: ["mounted static canvas", "stable chart box"],
      },
    };
    result.cases.push(staticRow);
    try {
      const before = await reflexState(page, "inline");
      check(!before.comm, "inline direct Chart unexpectedly has a live comm");
      await reflexToolbar(page, "inline", "zoomin");
      let after = await reflexState(page, "inline");
      check(!exact(after.ranges, before.ranges), "static Reflex toolbar zoom did not change ranges");
      assertEvent(after, "zoom_in", Object.keys(after.ranges));
      check(after.sends.length === 0 && after.jsonSafe, "static Reflex attempted transport or emitted unsafe JSON");
      await reflexToolbar(page, "inline", "reset");
      after = await reflexState(page, "inline");
      check(exact(after.ranges, before.ranges), "static Reflex reset did not restore home");
      assertEvent(after, "reset", Object.keys(after.ranges));
      check(near(before.layout.root.width, after.layout.root.width, 1e-4), "static Reflex layout width changed");
      check(after.layout.canvas.width > 100 && after.layout.canvas.height > 100, "static Reflex canvas is not laid out");
      staticRow.status = "passed";
      staticRow.metrics = { event_count: after.events.length, transport_messages: 0 };
    } catch (error) {
      staticRow.status = "failed";
      staticRow.error = String(error?.stack || error);
    }
    if (pageErrors.length) {
      result.page_errors = pageErrors;
      result.cases[0].status = "failed";
      result.cases[0].error = `Reflex page errors: ${pageErrors.join("; ")}`;
    }
    result.status = result.cases.every((item) => item.status === "passed") ? "passed" : "failed";
    await context.close();
  } catch (error) {
    result.status = "failed";
    result.error = String(error?.stack || error);
  } finally {
    await browser?.close();
  }
  return result;
}

async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  const matrixCatalog = catalog();
  validateCatalog(matrixCatalog);
  if (args.catalogOnly) {
    process.stdout.write(`${JSON.stringify(matrixCatalog, null, 2)}\n`);
    return 0;
  }
  if (args.verifyEvidence) {
    validateEvidence(JSON.parse(readFileSync(args.verifyEvidence, "utf8")));
    process.stdout.write(`pan/zoom evidence OK: ${args.verifyEvidence}\n`);
    return 0;
  }
  const selectedBrowsers = args.browsers
    ? args.browsers.split(",").filter(Boolean)
    : matrixCatalog.profiles[args.profile].browsers;
  for (const name of selectedBrowsers) check(ENGINE_NAMES.includes(name), `unknown browser ${name}`);
  check(
    equalSet(selectedBrowsers, matrixCatalog.profiles[args.profile].browsers),
    `${args.profile} profile requires browsers: ${matrixCatalog.profiles[args.profile].browsers.join(",")}`,
  );
  if (args.profile === "reflex") check(args.url, "reflex profile requires --url");

  const evidence = {
    schema_version: 1, requirement: "TST-NI-011", profile: args.profile,
    status: "running", generated_at: new Date().toISOString(), catalog: matrixCatalog,
    coverage: coverageFor(args.profile), browsers: {},
  };
  writeEvidence(args.evidence, evidence);
  try {
    for (const name of selectedBrowsers) {
      evidence.browsers[name] = args.profile === "reflex"
        ? await runReflexBrowser(name, args.url, args.executablePath)
        : await runStandaloneBrowser(name, args.profile, args.executablePath);
      writeEvidence(args.evidence, evidence);
    }
    evidence.status = Object.values(evidence.browsers).every((item) => item.status === "passed")
      ? "passed" : "failed";
    if (evidence.status === "passed") validateEvidence(evidence);
  } catch (error) {
    evidence.status = "failed";
    evidence.error = String(error?.stack || error);
  } finally {
    writeEvidence(args.evidence, evidence);
  }
  if (evidence.status !== "passed") {
    for (const [browserName, browser] of Object.entries(evidence.browsers)) {
      if (browser.error) process.stderr.write(`${browserName}: ${browser.error}\n`);
      for (const item of browser.cases || []) {
        if (item.status !== "passed") process.stderr.write(`${browserName}/${item.id}: ${item.error || item.status}\n`);
      }
    }
    return 1;
  }
  process.stdout.write(`pan/zoom ${args.profile} matrix OK: ${args.evidence}\n`);
  return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  process.exitCode = await main();
}
