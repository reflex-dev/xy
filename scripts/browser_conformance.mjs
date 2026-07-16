#!/usr/bin/env node
/** Accessibility and perceptual cross-browser smoke.
 *
 * This deliberately compares WebGL pixels through a coarse per-channel
 * signature and compares DOM chrome by layout boxes. Browser text glyphs are
 * not expected to be byte-identical (§21).
 */

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, firefox, webkit } from "playwright";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const BUNDLE = join(ROOT, "python", "xy", "static", "standalone.js");
const ENGINES = { chromium, firefox, webkit };
const headless = process.env.XY_CONFORMANCE_HEADFUL !== "1";
const selected = process.argv.find((arg) => arg.startsWith("--browsers="))?.split("=", 2)[1]
  ?.split(",").filter(Boolean) || Object.keys(ENGINES);
for (const name of selected) {
  if (!ENGINES[name]) throw new Error(`unknown browser ${name}; use chromium,firefox,webkit`);
}

const spec = {
  protocol: 3,
  width: 640,
  height: 360,
  title: "Cross-browser conformance",
  x_axis: { kind: "linear", label: "time", range: [-2, 2] },
  y_axis: { kind: "linear", label: "value", range: [-1, 3] },
  traces: [{
    id: 0,
    kind: "scatter",
    name: "observations",
    tier: "direct",
    n_points: 7,
    style: { opacity: 0.9 },
    color: { mode: "constant", color: "#2563eb" },
    size: { mode: "constant", size: 14 },
    x: 0,
    y: 1,
  }],
  columns: [
    { byte_offset: 0, len: 7, offset: 0, scale: 1, kind: "float" },
    { byte_offset: 28, len: 7, offset: 0, scale: 1, kind: "float" },
  ],
  interaction: { hover: true },
  backend: "none",
};
const values = [
  -1.8, -1.2, -0.5, 0, 0.55, 1.2, 1.8,
  0.2, 1.4, 0.7, 2.6, 1.1, 2.2, 0.4,
];

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

async function probe(name) {
  let browser;
  try {
    const launchOptions = { headless };
    if (name === "firefox") {
      // Firefox's Linux software-rendering blocklist can otherwise disable
      // WebGL in virtual displays even when Mesa is available.
      launchOptions.firefoxUserPrefs = {
        "webgl.disabled": false,
        "webgl.force-enabled": true,
      };
    }
    browser = await ENGINES[name].launch(launchOptions);
  } catch (error) {
    throw new Error(`${name} could not launch; run npx playwright install chromium firefox webkit\n${error}`);
  }
  const context = await browser.newContext({
    viewport: { width: 760, height: 480 },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.setContent("<!doctype html><meta charset=utf-8><body><div id=chart></div></body>");
  const hasWebGl2 = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2");
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
    return Boolean(gl);
  });
  if (!hasWebGl2) {
    await context.close();
    await browser.close();
    const mode = headless ? "headless" : "headful";
    throw new Error(`${name}: WebGL2 unavailable in ${mode} mode`);
  }
  await page.addScriptTag({ path: BUNDLE });
  await page.evaluate(({ spec, values }) => {
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
    const buffer = new Float32Array(values).buffer;
    window.xyConformanceView = window.xy.renderStandalone(
      document.getElementById("chart"), spec, buffer,
    );
    window.xyConformanceView.comm = { send() {} };
    window.xyConformanceLeaves = 0;
    window.xyConformanceView.root.addEventListener("xy:leave", () => {
      window.xyConformanceLeaves += 1;
    });
    HTMLCanvasElement.prototype.getContext = originalGetContext;
    window.xyConformanceView._drawNow();
  }, { spec, values });
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
  const result = await page.evaluate(() => {
    const v = window.xyConformanceView;
    const closedLive = v.a11yLive.textContent;
    v._onKernelMsg({
      type: "pick_result",
      seq: v._pickSeq - 1,
      row: { trace: 0, index: 1, x: -1.2, y: 1.4 },
    }, []);
    const staleExactIgnored =
      v.tooltip.style.display === "none" && v.a11yLive.textContent === closedLive;
    v._drawNow();
    const rect = (el) => {
      const r = el.getBoundingClientRect();
      const root = v.root.getBoundingClientRect();
      return {
        x: Math.round((r.x - root.x) * 10) / 10,
        y: Math.round((r.y - root.y) * 10) / 10,
        width: Math.round(r.width * 10) / 10,
        height: Math.round(r.height * 10) / 10,
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
    for (let i = 3; i < pixels.length; i += 4) if (pixels[i] > 8) lit += 1;
    for (let gy = 0; gy < rows; gy++) {
      for (let gx = 0; gx < cols; gx++) {
        const sums = [0, 0, 0, 0];
        let count = 0;
        const x0 = Math.floor(gx * width / cols), x1 = Math.floor((gx + 1) * width / cols);
        const y0 = Math.floor(gy * height / rows), y1 = Math.floor((gy + 1) * height / rows);
        for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
          const p = (y * width + x) * 4;
          for (let c = 0; c < 4; c++) sums[c] += pixels[p + c];
          count += 1;
        }
        signature.push(...sums.map((sum) => Math.round(sum / Math.max(1, count))));
      }
    }
    const before = { ...v.view };
    v._setView({ x0: -1, x1: 1, y0: 0, y1: 2 }, { animate: true });
    const reducedMotionSkippedAnimation = v._viewAnim === null;
    v.view = before;
    v.draw();
    const buttons = [...v._modebar.querySelectorAll("button")];
    return {
      semantics: {
        regionRole: v.root.getAttribute("role"),
        regionLabel: v.root.getAttribute("aria-label"),
        summary: v.a11ySummary.textContent,
        canvasRole: v.canvas.getAttribute("role"),
        canvasTabIndex: v.canvas.tabIndex,
        keyboardLive: window.xyConformanceKeyboardLive,
        closedLive,
        keyboardIndex: v._a11yPointIndex,
        hoverId: v._hoverId,
        leaveCount: window.xyConformanceLeaves,
        exactPreserved: window.xyConformanceExactPreserved,
        transitionSuppressed: window.xyConformanceTransitionSuppressed,
        staleExactIgnored,
        toolbarRole: v._modebar.getAttribute("role"),
        toolbarLabel: v._modebar.getAttribute("aria-label"),
        buttonLabels: buttons.map((button) =>
          button.getAttribute("aria-label") || button.textContent.trim() || button.title),
        pressed: buttons.filter((button) => button.getAttribute("aria-pressed") === "true")
          .map((button) =>
            button.getAttribute("aria-label") || button.textContent.trim() || button.title),
        reducedMotionSkippedAnimation,
      },
      layout: {
        root: rect(v.root),
        canvas: rect(v.canvas),
        toolbar: rect(v._modebar),
        title: rect(v.root.querySelector('[data-xy-slot="title"]')),
        labelPositions: [...v.labels.querySelectorAll('[data-xy-slot="tick_label"], [data-xy-slot="axis_title"]')]
          .map((el) => { const r = rect(el); return [r.x, r.y]; }),
      },
      signature,
      lit,
    };
  });
  await context.close();
  await browser.close();
  if (errors.length) throw new Error(`${name} page errors:\n${errors.join("\n")}`);
  const s = result.semantics;
  const semanticFailures = [];
  if (s.regionRole !== "region" || !s.regionLabel.includes("Cross-browser")) semanticFailures.push("chart region");
  if (!s.summary.includes("observations") || !s.summary.includes("X axis (time)")) semanticFailures.push("summary");
  if (s.canvasRole !== "img" || s.canvasTabIndex !== 0) semanticFailures.push("focusable plot image");
  if (s.keyboardIndex !== 1 || !s.keyboardLive.startsWith("Point 2 of 7.")) semanticFailures.push("keyboard/live readout");
  if (!s.exactPreserved) semanticFailures.push("exact reply announcement");
  if (!s.transitionSuppressed) semanticFailures.push("transition suppression");
  if (s.closedLive !== "Readout closed." || s.hoverId !== -1 || s.leaveCount !== 1) semanticFailures.push("Escape dismissal");
  if (!s.staleExactIgnored) semanticFailures.push("stale exact reply");
  if (s.toolbarRole !== "toolbar" || s.toolbarLabel !== "Chart controls") semanticFailures.push("toolbar");
  if (s.buttonLabels.length === 0 || s.buttonLabels.some((label) => !label)) semanticFailures.push("button names");
  if (s.pressed.length !== 1 || !s.pressed[0]) semanticFailures.push("toggle state");
  if (!s.reducedMotionSkippedAnimation) semanticFailures.push("reduced motion");
  if (semanticFailures.length) throw new Error(`${name} accessibility failures: ${semanticFailures.join(", ")}`);
  if (result.lit < 200) throw new Error(`${name} rendered only ${result.lit} lit WebGL pixels`);
  return result;
}

const results = {};
for (const name of selected) {
  results[name] = await probe(name);
  console.log(`${name}: semantics OK, ${results[name].lit} lit pixels`);
}
const referenceName = selected.includes("chromium") ? "chromium" : selected[0];
const reference = results[referenceName];
for (const name of selected) {
  if (name === referenceName) continue;
  const layoutDelta = maxLayoutDelta(reference, results[name]);
  const mae = signatureMae(reference, results[name]);
  const litRatio = results[name].lit / reference.lit;
  if (layoutDelta > 4) throw new Error(`${name}: DOM layout delta ${layoutDelta.toFixed(2)}px exceeds 4px`);
  if (mae > 12) throw new Error(`${name}: perceptual raster MAE ${mae.toFixed(2)} exceeds 12`);
  if (litRatio < 0.8 || litRatio > 1.2) {
    throw new Error(`${name}: lit-pixel ratio ${litRatio.toFixed(3)} is outside 0.8..1.2`);
  }
  console.log(`${name} vs ${referenceName}: layout Δ ${layoutDelta.toFixed(2)}px, raster MAE ${mae.toFixed(2)}, lit ratio ${litRatio.toFixed(3)}`);
}
console.log(`browser conformance OK: ${selected.join(", ")}`);
