#!/usr/bin/env node
/** Bounded semantic, layout, DPR, motion, and perceptual browser conformance.
 *
 * Every catalog case runs unchanged in Chromium, Firefox, and WebKit. WebGL
 * pixels are compared through a coarse per-channel signature and DOM chrome
 * through CSS-pixel layout boxes. Browser text glyphs are not expected to be
 * byte-identical (§21).
 */

import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, firefox, webkit } from "playwright";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const BUNDLE = join(ROOT, "python", "xy", "static", "standalone.js");
const protocolSource = readFileSync(join(ROOT, "python", "xy", "config.py"), "utf8");
const protocolMatch = protocolSource.match(/^PROTOCOL_VERSION\s*=\s*(\d+)\s*$/m);
if (!protocolMatch) throw new Error("could not read PROTOCOL_VERSION from python/xy/config.py");
const PROTOCOL_VERSION = Number(protocolMatch[1]);
const packageJson = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8"));

const ENGINES = { chromium, firefox, webkit };
const VIEWPORT = { width: 760, height: 480 };
const MAX_LAYOUT_DELTA = 4;
const MAX_SIGNATURE_MAE = 12;
const MIN_LIT_RATIO = 0.8;
const MAX_LIT_RATIO = 1.2;
const MIN_LIT_PIXELS = 80;
const REQUIRED_TIERS = ["direct", "decimated", "density"];
const REQUIRED_FAMILIES = ["scatter", "line", "bar", "heatmap", "mesh"];
const REQUIRED_DPRS = [1, 2];
const REQUIRED_MOTIONS = ["reduce", "no-preference"];
const REQUIRED_AXES = ["linear", "log", "category", "named"];
const EXPECTED_CASE_IDS = [
  "direct-linear-scatter-dpr1-reduced",
  "decimated-log-line-dpr2-motion",
  "direct-category-bar-dpr1-motion",
  "direct-linear-heatmap-dpr2-reduced",
  "direct-named-mesh-dpr1-motion",
  "density-linear-scatter-dpr2-reduced",
];

function axis(id, kind, label, range, extra = {}) {
  return { id, kind, label, range, side: id.startsWith("x") ? "bottom" : "left", ...extra };
}

function encodeColumn(definition) {
  if (definition.dtype === "u8") return Uint8Array.from(definition.values);
  const bytes = new Uint8Array(definition.values.length * 4);
  const view = new DataView(bytes.buffer);
  definition.values.forEach((value, index) => view.setFloat32(index * 4, value, true));
  return bytes;
}

function packColumns(definitions) {
  const encoded = definitions.map(encodeColumn);
  let length = 0;
  const columns = definitions.map((definition, index) => {
    length = Math.ceil(length / 4) * 4;
    const byteOffset = length;
    length += encoded[index].byteLength;
    if (definition.dtype === "u8") {
      return { byte_offset: byteOffset, len: definition.values.length, dtype: "u8" };
    }
    return {
      byte_offset: byteOffset,
      len: definition.values.length,
      offset: definition.offset ?? 0,
      scale: definition.scale ?? 1,
      kind: definition.kind || "float",
    };
  });
  const bytes = new Uint8Array(length);
  columns.forEach((column, index) => bytes.set(encoded[index], column.byte_offset));
  return { columns, bytes: [...bytes] };
}

function fixture({ title, axes, traces, columns }) {
  const packed = packColumns(columns);
  return {
    spec: {
      protocol: PROTOCOL_VERSION,
      width: 640,
      height: 360,
      title,
      x_axis: axes.x,
      y_axis: axes.y,
      axes,
      traces,
      columns: packed.columns,
      interaction: { hover: true },
      backend: "none",
      show_legend: true,
      view: { ranges: Object.fromEntries(Object.entries(axes).map(([id, value]) => [id, value.range])) },
    },
    bytes: packed.bytes,
  };
}

function caseDefinition(metadata, build) {
  return { ...metadata, build };
}

const CASES = [
  caseDefinition({
    id: EXPECTED_CASE_IDS[0],
    tier: "direct",
    family: "scatter",
    dpr: 1,
    motion: "reduce",
    axisClasses: ["linear"],
    anchor: true,
    expectedKind: "scatter",
    expectedTraceAxes: ["x", "y"],
    expectedAxisTitles: ["time", "value"],
    expectedSummary: ["observations", "X axis (time)"],
  }, () => fixture({
    title: "Cross-browser conformance",
    axes: {
      x: axis("x", "linear", "time", [-2, 2]),
      y: axis("y", "linear", "value", [-1, 3]),
    },
    traces: [{
      id: 0,
      kind: "scatter",
      name: "observations",
      tier: "direct",
      n_points: 7,
      n_marks: 7,
      style: { opacity: 0.9 },
      color: { mode: "constant", color: "#2563eb" },
      size: { mode: "constant", size: 14 },
      x: 0,
      y: 1,
      x_axis: "x",
      y_axis: "y",
    }],
    columns: [
      { values: [-1.8, -1.2, -0.5, 0, 0.55, 1.2, 1.8] },
      { values: [0.2, 1.4, 0.7, 2.6, 1.1, 2.2, 0.4] },
    ],
  })),
  caseDefinition({
    id: EXPECTED_CASE_IDS[1],
    tier: "decimated",
    family: "line",
    dpr: 2,
    motion: "no-preference",
    axisClasses: ["log"],
    expectedKind: "line",
    expectedTraceAxes: ["x", "y"],
    expectedAxisTitles: ["log x", "line y"],
    expectedSummary: ["decimated line", "X axis (log x)"],
  }, () => {
    const xs = Array.from({ length: 64 }, (_, index) => 10 ** (2 * index / 63));
    const ys = xs.map((_, index) => 1.2 + 0.65 * Math.sin(index * 0.42));
    return fixture({
      title: "Decimated log line",
      axes: {
        x: axis("x", "linear", "log x", [1, 100], { scale: "log" }),
        y: axis("y", "linear", "line y", [0.4, 2]),
      },
      traces: [{
        id: 0,
        kind: "line",
        name: "decimated line",
        tier: "decimated",
        n_points: 20_000,
        n_marks: xs.length,
        style: { color: "#dc2626", width: 3, opacity: 1 },
        x: 0,
        y: 1,
        x_axis: "x",
        y_axis: "y",
      }],
      columns: [{ values: xs }, { values: ys }],
    });
  }),
  caseDefinition({
    id: EXPECTED_CASE_IDS[2],
    tier: "direct",
    family: "bar",
    dpr: 1,
    motion: "no-preference",
    axisClasses: ["category"],
    expectedKind: "bar",
    expectedTraceAxes: ["x", "y"],
    expectedAxisTitles: ["category", "amount"],
    expectedTickLabels: ["alpha", "beta", "gamma"],
    expectedSummary: ["category bars", "X axis (category)"],
  }, () => fixture({
    title: "Category bar",
    axes: {
      x: axis("x", "category", "category", [-0.5, 2.5], {
        categories: ["alpha", "beta", "gamma"],
      }),
      y: axis("y", "linear", "amount", [0, 2.2]),
    },
    traces: [{
      id: 0,
      kind: "bar",
      name: "category bars",
      tier: "direct",
      n_points: 3,
      n_marks: 3,
      style: {
        color: "#4f46e5",
        opacity: 0.85,
        role: "bar",
        orientation: "vertical",
      },
      x_axis: "x",
      y_axis: "y",
      bar: {
        orientation: "vertical",
        value_axis: "y",
        pos: 0,
        value1: 1,
        width: 0.8,
        value0_const: 0,
      },
    }],
    columns: [{ values: [0, 1, 2] }, { values: [1, 2, 1.5] }],
  })),
  caseDefinition({
    id: EXPECTED_CASE_IDS[3],
    tier: "direct",
    family: "heatmap",
    dpr: 2,
    motion: "reduce",
    axisClasses: ["linear"],
    expectedKind: "heatmap",
    expectedTraceAxes: ["x", "y"],
    expectedAxisTitles: ["heat x", "heat y"],
    expectedSummary: ["heat values", "X axis (heat x)"],
  }, () => fixture({
    title: "Linear heatmap",
    axes: {
      x: axis("x", "linear", "heat x", [-0.5, 3.5]),
      y: axis("y", "linear", "heat y", [-0.5, 2.5]),
    },
    traces: [{
      id: 0,
      kind: "heatmap",
      name: "heat values",
      tier: "direct",
      n_points: 12,
      n_marks: 12,
      x_axis: "x",
      y_axis: "y",
      style: {
        opacity: 0.95,
        role: "heatmap",
        colormap: "viridis",
        domain: [0, 5],
        truecolor: false,
        x_range: [-0.5, 3.5],
        y_range: [-0.5, 2.5],
      },
      heatmap: {
        buf: 0,
        w: 4,
        h: 3,
        x_range: [-0.5, 3.5],
        y_range: [-0.5, 2.5],
        colormap: "viridis",
        domain: [0, 5],
      },
      color: { mode: "continuous", colormap: "viridis", domain: [0, 5] },
    }],
    columns: [{ values: [0, 1, 3, 5, 1, 4, 2, 0, 3, 2, 5, 1] }],
  })),
  caseDefinition({
    id: EXPECTED_CASE_IDS[4],
    tier: "direct",
    family: "mesh",
    dpr: 1,
    motion: "no-preference",
    axisClasses: ["named"],
    expectedKind: "triangle_mesh",
    expectedTraceAxes: ["x2", "y2"],
    expectedAxisTitles: ["base x", "base y", "named x", "named y"],
    expectedSummary: ["named mesh", "X axis (base x)"],
  }, () => fixture({
    title: "Named-axis mesh",
    axes: {
      x: axis("x", "linear", "base x", [0, 1]),
      y: axis("y", "linear", "base y", [0, 1]),
      x2: axis("x2", "linear", "named x", [0, 1], { side: "top" }),
      y2: axis("y2", "linear", "named y", [0, 1], { side: "right" }),
    },
    traces: [{
      id: 0,
      kind: "triangle_mesh",
      name: "named mesh",
      tier: "direct",
      n_points: 2,
      n_marks: 2,
      x_axis: "x2",
      y_axis: "y2",
      x0: 0,
      x1: 1,
      x2: 2,
      y0: 3,
      y1: 4,
      y2: 5,
      style: { opacity: 1, role: "triangle-mesh", stroke: "#334155", stroke_width: 1 },
      color: { mode: "continuous", colormap: "viridis", domain: [0.2, 0.8], buf: 6 },
    }],
    columns: [
      { values: [0, 1] },
      { values: [1, 1] },
      { values: [0, 0] },
      { values: [0, 0] },
      { values: [0, 1] },
      { values: [1, 1] },
      { values: [0.2, 0.8] },
    ],
  })),
  caseDefinition({
    id: EXPECTED_CASE_IDS[5],
    tier: "density",
    family: "scatter",
    dpr: 2,
    motion: "reduce",
    axisClasses: ["linear"],
    expectedKind: "scatter",
    expectedTraceAxes: ["x", "y"],
    expectedAxisTitles: ["density x", "density y"],
    expectedSummary: ["density cloud", "X axis (density x)"],
  }, () => {
    const width = 32;
    const height = 20;
    const grid = [];
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const dx = (x - width * 0.5) / (width * 0.22);
        const dy = (y - height * 0.5) / (height * 0.28);
        grid.push(Math.max(0, Math.round(255 * Math.exp(-(dx * dx + dy * dy)))));
      }
    }
    return fixture({
      title: "Density tier",
      axes: {
        x: axis("x", "linear", "density x", [-2, 2]),
        y: axis("y", "linear", "density y", [-1, 1]),
      },
      traces: [{
        id: 0,
        kind: "scatter",
        name: "density cloud",
        tier: "density",
        n_points: 250_000,
        n_marks: width * height,
        visible: 250_000,
        x_axis: "x",
        y_axis: "y",
        style: { opacity: 0.9 },
        density: {
          buf: 0,
          w: width,
          h: height,
          max: 40,
          enc: "log-u8",
          colormap: "viridis",
          x_range: [-2, 2],
          y_range: [-1, 1],
          channels_dropped: false,
          dropped_channels: [],
        },
      }],
      columns: [{ dtype: "u8", values: grid }],
    });
  }),
];

function optionValue(name) {
  const exact = process.argv.indexOf(name);
  if (exact >= 0) return process.argv[exact + 1];
  return process.argv.find((argument) => argument.startsWith(`${name}=`))?.slice(name.length + 1);
}

const headless = process.env.XY_CONFORMANCE_HEADFUL !== "1";
const selected = (optionValue("--browsers") || Object.keys(ENGINES).join(","))
  .split(",").filter(Boolean);
const evidencePathValue = optionValue("--evidence") || process.env.XY_CONFORMANCE_EVIDENCE;
const evidencePath = evidencePathValue ? resolve(evidencePathValue) : null;

function metadataOf(caseItem) {
  const {
    build: _build,
    expectedSummary: _expectedSummary,
    expectedAxisTitles: _expectedAxisTitles,
    expectedTickLabels: _expectedTickLabels,
    expectedKind: _expectedKind,
    expectedTraceAxes: _expectedTraceAxes,
    anchor: _anchor,
    ...metadata
  } = caseItem;
  return metadata;
}

function requireCoverage(cases, field, required) {
  const observed = new Set(cases.flatMap((caseItem) => caseItem[field]));
  const missing = required.filter((value) => !observed.has(value));
  if (missing.length) throw new Error(`browser conformance catalog missing ${field}: ${missing.join(", ")}`);
}

function validateCatalog(cases = CASES) {
  const ids = cases.map((caseItem) => caseItem.id);
  if (new Set(ids).size !== ids.length) throw new Error("browser conformance case IDs must be unique");
  if (ids.join("\n") !== EXPECTED_CASE_IDS.join("\n")) {
    throw new Error(`browser conformance catalog IDs differ: ${ids.join(", ")}`);
  }
  requireCoverage(cases, "tier", REQUIRED_TIERS);
  requireCoverage(cases, "family", REQUIRED_FAMILIES);
  requireCoverage(cases, "dpr", REQUIRED_DPRS);
  requireCoverage(cases, "motion", REQUIRED_MOTIONS);
  requireCoverage(cases, "axisClasses", REQUIRED_AXES);
  for (const caseItem of cases) {
    if (typeof caseItem.build !== "function") throw new Error(`${caseItem.id}: missing fixture builder`);
    const built = caseItem.build();
    if (built.spec.traces.length !== 1) throw new Error(`${caseItem.id}: expected one trace`);
    const trace = built.spec.traces[0];
    if (trace.tier !== caseItem.tier || trace.kind !== caseItem.expectedKind) {
      throw new Error(`${caseItem.id}: fixture metadata does not match its trace`);
    }
  }
}

function maxLayoutDelta(base, candidate) {
  let worst = 0;
  for (const key of ["root", "canvas", "toolbar", "title"]) {
    for (const field of ["x", "y", "width", "height"]) {
      worst = Math.max(worst, Math.abs(base.layout[key][field] - candidate.layout[key][field]));
    }
  }
  if (base.layout.labelPositions.length !== candidate.layout.labelPositions.length) return Infinity;
  for (let i = 0; i < base.layout.labelPositions.length; i++) {
    worst = Math.max(
      worst,
      Math.abs(base.layout.labelPositions[i][0] - candidate.layout.labelPositions[i][0]),
      Math.abs(base.layout.labelPositions[i][1] - candidate.layout.labelPositions[i][1]),
    );
  }
  return worst;
}

function signatureMae(base, candidate) {
  if (base.signature.length !== candidate.signature.length) return Infinity;
  let error = 0;
  for (let i = 0; i < base.signature.length; i++) {
    error += Math.abs(base.signature[i] - candidate.signature[i]);
  }
  return error / base.signature.length;
}

function compareResults(reference, candidate) {
  const layoutDelta = maxLayoutDelta(reference, candidate);
  const mae = signatureMae(reference, candidate);
  const litRatio = candidate.lit / reference.lit;
  const failures = [];
  if (layoutDelta > MAX_LAYOUT_DELTA) {
    failures.push(`DOM layout delta ${layoutDelta.toFixed(2)}px exceeds ${MAX_LAYOUT_DELTA}px`);
  }
  if (mae > MAX_SIGNATURE_MAE) {
    failures.push(`perceptual raster MAE ${mae.toFixed(2)} exceeds ${MAX_SIGNATURE_MAE}`);
  }
  if (litRatio < MIN_LIT_RATIO || litRatio > MAX_LIT_RATIO) {
    failures.push(`lit-pixel ratio ${litRatio.toFixed(3)} is outside ${MIN_LIT_RATIO}..${MAX_LIT_RATIO}`);
  }
  return { layoutDelta, rasterMae: mae, litRatio, failures };
}

function staticNegativeControls() {
  let catalogGapRejected = false;
  try {
    validateCatalog(CASES.slice(0, -1));
  } catch {
    catalogGapRejected = true;
  }
  if (!catalogGapRejected) throw new Error("catalog-gap negative control was not rejected");

  const base = {
    layout: {
      root: { x: 0, y: 0, width: 10, height: 10 },
      canvas: { x: 1, y: 1, width: 8, height: 8 },
      toolbar: { x: 1, y: 1, width: 2, height: 2 },
      title: { x: 3, y: 1, width: 4, height: 1 },
      labelPositions: [[1, 9]],
    },
    signature: Array(32).fill(0),
    lit: 100,
  };
  const corruptedSignature = {
    ...base,
    signature: Array(32).fill(255),
  };
  const corruptedLayout = {
    ...base,
    layout: {
      ...base.layout,
      root: { ...base.layout.root, x: 10 },
    },
  };
  const corruptedSignatureRejected = compareResults(base, corruptedSignature).failures
    .some((failure) => failure.includes("raster MAE"));
  const corruptedLayoutRejected = compareResults(base, corruptedLayout).failures
    .some((failure) => failure.includes("layout delta"));
  if (!corruptedSignatureRejected || !corruptedLayoutRejected) {
    throw new Error("cross-browser comparator negative controls were not rejected");
  }
  return { catalogGapRejected, corruptedSignatureRejected, corruptedLayoutRejected };
}

function semanticFailures(caseItem, result) {
  const s = result.semantics;
  const failures = [];
  if (s.regionRole !== "region" || !s.regionLabel.includes(result.title)) failures.push("chart region");
  if (caseItem.expectedSummary.some((token) => !s.summary.includes(token))) failures.push("summary");
  if (s.canvasRole !== "img" || s.canvasTabIndex !== 0) failures.push("focusable plot image");
  if (s.toolbarRole !== "toolbar" || s.toolbarLabel !== "Chart controls") failures.push("toolbar");
  if (s.buttonLabels.length === 0 || s.buttonLabels.some((label) => !label)) failures.push("button names");
  if (s.pressed.length !== 1 || !s.pressed[0]) failures.push("toggle state");
  if (s.mediaReduced !== (caseItem.motion === "reduce")) failures.push("media preference");
  if (s.animationActive !== (caseItem.motion === "no-preference")) failures.push("view animation preference");
  if (result.observedDpr !== caseItem.dpr || !result.backingStoreMatchesDpr) failures.push("DPR backing store");
  if (result.gpu.kind !== caseItem.expectedKind || result.gpu.tier !== caseItem.tier) failures.push("GPU trace contract");
  if (result.gpu.xAxis !== caseItem.expectedTraceAxes[0]
      || result.gpu.yAxis !== caseItem.expectedTraceAxes[1]) failures.push("trace axis binding");
  for (const title of caseItem.expectedAxisTitles) {
    if (!result.axisTitles.includes(title)) failures.push(`axis title ${title}`);
  }
  for (const label of caseItem.expectedTickLabels || []) {
    if (!result.tickLabels.includes(label)) failures.push(`tick label ${label}`);
  }
  if (caseItem.anchor) {
    if (s.keyboardIndex !== 1 || !s.keyboardLive.startsWith("Point 2 of 7.")) {
      failures.push("keyboard/live readout");
    }
    if (!s.exactPreserved) failures.push("exact reply announcement");
    if (!s.transitionSuppressed) failures.push("transition suppression");
    if (s.closedLive !== "Readout closed." || s.hoverId !== -1 || s.leaveCount !== 1) {
      failures.push("Escape dismissal");
    }
    if (!s.staleExactIgnored) failures.push("stale exact reply");
  }
  if (result.layout.root.width <= 0 || result.layout.canvas.width <= 0) failures.push("nonzero layout");
  if (result.lit < MIN_LIT_PIXELS) failures.push(`only ${result.lit} lit WebGL pixels`);
  return failures;
}

async function launchEngine(name) {
  const launchOptions = { headless };
  if (name === "firefox") {
    // Firefox's Linux software-rendering blocklist can otherwise disable
    // WebGL in virtual displays even when Mesa is available.
    launchOptions.firefoxUserPrefs = {
      "webgl.disabled": false,
      "webgl.force-enabled": true,
    };
  }
  try {
    return await ENGINES[name].launch(launchOptions);
  } catch (error) {
    throw new Error(`${name} could not launch; run npx playwright install chromium firefox webkit\n${error}`);
  }
}

async function probeCase(browser, engineName, caseItem) {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: caseItem.dpr,
    reducedMotion: caseItem.motion,
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  try {
    await page.setContent("<!doctype html><meta charset=utf-8><body><div id=chart></div></body>");
    const hasWebGl2 = await page.evaluate(() => {
      const canvas = document.createElement("canvas");
      const gl = canvas.getContext("webgl2");
      gl?.getExtension("WEBGL_lose_context")?.loseContext();
      return Boolean(gl);
    });
    if (!hasWebGl2) {
      const mode = headless ? "headless" : "headful";
      throw new Error(`${engineName}: WebGL2 unavailable in ${mode} mode`);
    }
    await page.addScriptTag({ path: BUNDLE });
    const built = caseItem.build();
    await page.evaluate(({ spec, bytes }) => {
      // The shipped client correctly uses the faster discardable default
      // framebuffer. Preserve it only inside this probe so readPixels observes
      // the same completed frame after browser compositing in every engine.
      const originalGetContext = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function(type, attributes) {
        if (type === "webgl2") {
          return originalGetContext.call(this, type, { ...attributes, preserveDrawingBuffer: true });
        }
        return originalGetContext.call(this, type, attributes);
      };
      try {
        window.xyConformanceView = window.xy.renderStandalone(
          document.getElementById("chart"), spec, new Uint8Array(bytes).buffer,
        );
        window.xyConformanceView.comm = { send() {} };
        window.xyConformanceLeaves = 0;
        window.xyConformanceView.root.addEventListener("xy:leave", () => {
          window.xyConformanceLeaves += 1;
        });
        window.xyConformanceView._drawNow();
      } finally {
        HTMLCanvasElement.prototype.getContext = originalGetContext;
      }
    }, built);
    await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));

    if (caseItem.anchor) {
      await page.locator('[data-xy-slot="canvas"]').focus();
      await page.keyboard.press("Home");
      await page.keyboard.press("ArrowRight");
      await page.evaluate(() => {
        const v = window.xyConformanceView;
        window.xyConformanceKeyboardLive = v.a11yLive.textContent;
        v._onKernelMsg({
          type: "pick_result",
          seq: v._pickSeq,
          row: { trace: 0, index: 1, x: -1.2, y: 1.4 },
        }, []);
        window.xyConformanceExactPreserved =
          v.a11yLive.textContent === window.xyConformanceKeyboardLive;
        const index = v._a11yPointIndex;
        const live = v.a11yLive.textContent;
        v._viewAnim = {};
        v._onA11yKey({ key: "ArrowRight", preventDefault() {} });
        window.xyConformanceTransitionSuppressed =
          v._a11yPointIndex === index && v.a11yLive.textContent === live;
        v._viewAnim = null;
      });
      await page.keyboard.press("Escape");
    }

    const result = await page.evaluate(({ anchor, requestedMotion }) => {
      const v = window.xyConformanceView;
      let closedLive = null;
      let staleExactIgnored = true;
      if (anchor) {
        closedLive = v.a11yLive.textContent;
        v._onKernelMsg({
          type: "pick_result",
          seq: v._pickSeq - 1,
          row: { trace: 0, index: 1, x: -1.2, y: 1.4 },
        }, []);
        staleExactIgnored =
          v.tooltip.style.display === "none" && v.a11yLive.textContent === closedLive;
      }
      v._drawNow();
      const rect = (element) => {
        const value = element.getBoundingClientRect();
        const root = v.root.getBoundingClientRect();
        return {
          x: Math.round((value.x - root.x) * 10) / 10,
          y: Math.round((value.y - root.y) * 10) / 10,
          width: Math.round(value.width * 10) / 10,
          height: Math.round(value.height * 10) / 10,
        };
      };
      const gl = v.gl;
      const width = gl.drawingBufferWidth;
      const height = gl.drawingBufferHeight;
      const pixels = new Uint8Array(width * height * 4);
      gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      const cols = 32;
      const rows = 20;
      const signature = [];
      let lit = 0;
      for (let index = 3; index < pixels.length; index += 4) if (pixels[index] > 8) lit += 1;
      for (let gy = 0; gy < rows; gy++) {
        for (let gx = 0; gx < cols; gx++) {
          const sums = [0, 0, 0, 0];
          let count = 0;
          const x0 = Math.floor(gx * width / cols), x1 = Math.floor((gx + 1) * width / cols);
          const y0 = Math.floor(gy * height / rows), y1 = Math.floor((gy + 1) * height / rows);
          for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
            const pixel = (y * width + x) * 4;
            for (let channel = 0; channel < 4; channel++) sums[channel] += pixels[pixel + channel];
            count += 1;
          }
          signature.push(...sums.map((sum) => Math.round(sum / Math.max(1, count))));
        }
      }

      const before = JSON.parse(JSON.stringify(v.view));
      const ranges = Object.fromEntries(v._axisIds().map((axisId) => {
        const [lo, hi] = v._axisRange(axisId);
        const inset = (hi - lo) * 0.12;
        return [axisId, [lo + inset, hi - inset]];
      }));
      v._setView({ ranges }, { animate: true, request: false, history: false });
      const animationActive = v._viewAnim !== null;
      v._cancelViewAnimation();
      v.view = before;
      v._drawNow();

      const buttons = [...v._modebar.querySelectorAll("button")];
      const canvasRect = v.canvas.getBoundingClientRect();
      const gpu = v.gpuTraces[0];
      return {
        title: v.spec.title,
        semantics: {
          regionRole: v.root.getAttribute("role"),
          regionLabel: v.root.getAttribute("aria-label"),
          summary: v.a11ySummary.textContent,
          canvasRole: v.canvas.getAttribute("role"),
          canvasTabIndex: v.canvas.tabIndex,
          keyboardLive: window.xyConformanceKeyboardLive || "",
          closedLive,
          keyboardIndex: v._a11yPointIndex,
          hoverId: v._hoverId,
          leaveCount: window.xyConformanceLeaves,
          exactPreserved: window.xyConformanceExactPreserved ?? true,
          transitionSuppressed: window.xyConformanceTransitionSuppressed ?? true,
          staleExactIgnored,
          toolbarRole: v._modebar.getAttribute("role"),
          toolbarLabel: v._modebar.getAttribute("aria-label"),
          buttonLabels: buttons.map((button) =>
            button.getAttribute("aria-label") || button.textContent.trim() || button.title),
          pressed: buttons.filter((button) => button.getAttribute("aria-pressed") === "true")
            .map((button) =>
              button.getAttribute("aria-label") || button.textContent.trim() || button.title),
          mediaReduced: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
          requestedMotion,
          animationActive,
        },
        layout: {
          root: rect(v.root),
          canvas: rect(v.canvas),
          toolbar: rect(v._modebar),
          title: rect(v.root.querySelector('[data-xy-slot="title"]')),
          labelPositions: [...v.labels.querySelectorAll(
            '[data-xy-slot="tick_label"], [data-xy-slot="axis_title"]',
          )].map((element) => { const value = rect(element); return [value.x, value.y]; }),
        },
        gpu: {
          kind: gpu.trace.kind,
          tier: gpu.tier,
          xAxis: gpu.xAxis,
          yAxis: gpu.yAxis,
        },
        axisTitles: [...v.labels.querySelectorAll('[data-xy-slot="axis_title"]')]
          .map((element) => element.textContent),
        tickLabels: [...v.labels.querySelectorAll('[data-xy-slot="tick_label"]')]
          .map((element) => element.textContent),
        observedDpr: window.devicePixelRatio,
        backingStoreMatchesDpr:
          Math.abs(width - canvasRect.width * window.devicePixelRatio) <= 2
          && Math.abs(height - canvasRect.height * window.devicePixelRatio) <= 2,
        drawingBuffer: { width, height },
        signature,
        lit,
      };
    }, { anchor: Boolean(caseItem.anchor), requestedMotion: caseItem.motion });

    if (errors.length) throw new Error(`${engineName}/${caseItem.id} page errors:\n${errors.join("\n")}`);
    const failures = semanticFailures(caseItem, result);
    if (failures.length) {
      throw new Error(`${engineName}/${caseItem.id} semantic failures: ${failures.join(", ")}`);
    }
    return result;
  } finally {
    await page.evaluate(() => window.xyConformanceView?.destroy()).catch(() => {});
    await context.close();
  }
}

function resultForEvidence(result) {
  const { signature, ...summary } = result;
  return {
    ...summary,
    signatureSha256: createHash("sha256").update(Uint8Array.from(signature)).digest("hex"),
  };
}

function writeEvidence(evidence) {
  if (!evidencePath) return;
  mkdirSync(dirname(evidencePath), { recursive: true });
  writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`);
}

async function runConformance() {
  const evidence = {
    schema: "xy-browser-conformance/v1",
    status: "started",
    environment: {
      node: process.version,
      platform: process.platform,
      arch: process.arch,
      playwright: packageJson.devDependencies.playwright,
      mode: headless ? "headless" : "headful",
      viewport: VIEWPORT,
      selectedEngines: selected,
      skipPolicy: "none; missing selected engines or WebGL2 fail",
    },
    thresholds: {
      maxLayoutDeltaCssPx: MAX_LAYOUT_DELTA,
      maxSignatureMae: MAX_SIGNATURE_MAE,
      litPixelRatio: [MIN_LIT_RATIO, MAX_LIT_RATIO],
      minLitPixels: MIN_LIT_PIXELS,
    },
    matrix: CASES.map(metadataOf),
    engines: {},
    comparisons: {},
    negativeControls: {},
  };
  writeEvidence(evidence);
  const results = {};
  try {
    validateCatalog();
    for (const name of selected) {
      if (!ENGINES[name]) throw new Error(`unknown browser ${name}; use chromium,firefox,webkit`);
    }
    if (!selected.length) throw new Error("at least one browser engine is required");
    evidence.negativeControls = staticNegativeControls();
    for (const name of selected) {
      const engineEvidence = { status: "started", version: null, cases: {} };
      evidence.engines[name] = engineEvidence;
      writeEvidence(evidence);
      let browser;
      try {
        browser = await launchEngine(name);
        engineEvidence.version = browser.version();
        results[name] = {};
        for (const caseItem of CASES) {
          const result = await probeCase(browser, name, caseItem);
          results[name][caseItem.id] = result;
          engineEvidence.cases[caseItem.id] = resultForEvidence(result);
          console.log(`${name}/${caseItem.id}: semantics OK, ${result.lit} lit pixels`);
          writeEvidence(evidence);
        }
        engineEvidence.status = "passed";
      } catch (error) {
        engineEvidence.status = "failed";
        engineEvidence.error = String(error?.stack || error);
        throw error;
      } finally {
        await browser?.close();
      }
    }

    const referenceName = selected.includes("chromium") ? "chromium" : selected[0];
    for (const caseItem of CASES) {
      evidence.comparisons[caseItem.id] = {};
      const reference = results[referenceName][caseItem.id];
      for (const name of selected) {
        if (name === referenceName) continue;
        const comparison = compareResults(reference, results[name][caseItem.id]);
        evidence.comparisons[caseItem.id][name] = {
          reference: referenceName,
          layoutDeltaCssPx: comparison.layoutDelta,
          rasterMae: comparison.rasterMae,
          litPixelRatio: comparison.litRatio,
        };
        if (comparison.failures.length) {
          throw new Error(`${name}/${caseItem.id} vs ${referenceName}: ${comparison.failures.join(", ")}`);
        }
        console.log(
          `${name}/${caseItem.id} vs ${referenceName}: layout Δ ${comparison.layoutDelta.toFixed(2)}px, `
          + `raster MAE ${comparison.rasterMae.toFixed(2)}, lit ratio ${comparison.litRatio.toFixed(3)}`,
        );
      }
    }
    evidence.status = "passed";
    console.log(`browser conformance OK: ${CASES.length} cases × ${selected.length} engines`);
  } catch (error) {
    evidence.status = "failed";
    evidence.error = String(error?.stack || error);
    throw error;
  } finally {
    writeEvidence(evidence);
  }
}

if (process.argv.includes("--list-cases")) {
  validateCatalog();
  console.log(JSON.stringify(CASES.map(metadataOf), null, 2));
} else if (process.argv.includes("--self-test")) {
  validateCatalog();
  console.log(JSON.stringify(staticNegativeControls(), null, 2));
} else {
  await runConformance();
}
