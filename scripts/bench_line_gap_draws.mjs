import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { chromium } from "playwright";

const [directory, output] = process.argv.slice(2);
if (!directory || !output) {
  throw new Error("usage: node scripts/bench_line_gap_draws.mjs FIXTURE_DIRECTORY OUTPUT_JSON");
}
const root = resolve(directory);
const patterns = ["finite", "one_gap", "fragmented"];
const server = createServer(async (request, response) => {
  const name = new URL(request.url, "http://localhost").pathname.slice(1);
  if (!patterns.some((pattern) => name === `${pattern}.html`)) {
    response.writeHead(404).end();
    return;
  }
  response.setHeader("Content-Type", "text/html");
  response.end(await readFile(`${root}/${name}`));
});
await new Promise((done) => server.listen(0, "127.0.0.1", done));
const browser = await chromium.launch({
  executablePath: process.env.XY_CHROMIUM || "/usr/bin/chromium",
  headless: true,
  args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
const started = new Date().toISOString();
const records = [];
try {
  for (const pattern of patterns) {
    for (const width of [720, 380]) {
      const page = await browser.newPage({
        viewport: { width: 900, height: 600 }, deviceScaleFactor: 1,
      });
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const began = performance.now();
      await page.goto(`http://127.0.0.1:${server.address().port}/${pattern}.html`);
      await page.waitForFunction(() => window.liveGapView?.gpuTraces?.length);
      const startupMs = performance.now() - began;
      const result = await page.evaluate(async (width) => {
        const view = window.liveGapView;
        view.fluid = true;
        view.fluidH = true;
        view.root.style.width = `${width}px`;
        view._resize(width, 320);
        if (view._raf) cancelAnimationFrame(view._raf);
        view._raf = null;
        view._drawNow();
        view.gl.finish();
        const gl = view.gl;
        const debug = gl.getExtension("WEBGL_debug_renderer_info");
        let instanced = 0, plain = 0;
        const draw = gl.drawArraysInstanced, drawPlain = gl.drawArrays;
        gl.drawArraysInstanced = function(...args) {
          instanced++;
          return draw.apply(this, args);
        };
        gl.drawArrays = function(...args) {
          plain++;
          return drawPlain.apply(this, args);
        };
        const samples = [];
        for (let i = 0; i < 11; i++) {
          instanced = 0;
          plain = 0;
          const start = performance.now();
          view._drawNow();
          const submitted = performance.now();
          gl.finish();
          if (i >= 3) samples.push({
            cpuDrawMs: submitted - start, finishedMs: performance.now() - start,
            instancedCalls: instanced, plainCalls: plain,
          });
        }
        gl.drawArraysInstanced = draw;
        gl.drawArrays = drawPlain;
        const intervals = [];
        let previous;
        await new Promise((done) => {
          let i = 0;
          function frame(now) {
            if (previous !== undefined && i > 4) intervals.push(now - previous);
            previous = now;
            view._drawNow();
            i++;
            if (i < 25) requestAnimationFrame(frame);
            else done();
          }
          requestAnimationFrame(frame);
        });
        const box = view.root.getBoundingClientRect();
        const canvas = view.canvas.getBoundingClientRect();
        const trace = view.gpuTraces[0];
        const hover = view._hover;
        view._hover = function(event) {
          const start = performance.now();
          const result = hover.call(this, event);
          window.lastHoverHandlerMs = performance.now() - start;
          return result;
        };
        window.liveGapPump = true;
        function pump() {
          if (!window.liveGapPump) return;
          view._drawNow();
          requestAnimationFrame(pump);
        }
        requestAnimationFrame(pump);
        const targets = [0.15, 0.3, 0.45, 0.65, 0.8].map((fraction) => {
          const row = Math.floor((trace._cpu.x.length - 1) * fraction);
          const x = view._decodeValue(trace._cpu.x, trace.xMeta, row);
          const y = view._decodeValue(trace._cpu.y, trace.yMeta, row);
          const point = view._projectDataPoint(trace.xAxis, trace.yAxis, x, y);
          return {
            x: canvas.left + point[0] - view.plot.x,
            y: canvas.top + point[1] - view.plot.y,
            source: trace._sourceRows?.[row] ?? row,
          };
        });
        return {
          samples, intervals, targets,
          indexSpace: trace._sourceRows ? "canonical" : "emitted",
          shape: {
            width: box.width, height: box.height,
            canvasWidth: view.canvas.width, canvasHeight: view.canvas.height,
            dpr: view.dpr,
            visible: box.left >= 0 && box.top >= 0 && box.right <= innerWidth && box.bottom <= innerHeight,
          },
          visibilityState: document.visibilityState,
          marks: trace._cpu.x.length, runs: trace._lineRanges?.length ?? 1,
          modebar: view.spec.show_modebar, legend: view.spec.show_legend,
          renderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : null,
          vendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : null,
          glVersion: gl.getParameter(gl.VERSION), glError: gl.getError(),
        };
      }, width);
      assert.ok(result.shape.visible && result.shape.dpr === 1);
      assert.equal(result.visibilityState, "visible");
      assert.equal(result.modebar, false);
      assert.equal(result.legend, false);
      assert.equal(result.glError, 0);
      assert.ok(result.renderer?.includes("SwiftShader"));
      const hover = [];
      for (const target of result.targets) {
        const start = performance.now();
        await page.mouse.move(target.x, target.y);
        const state = await page.evaluate(() => ({
          row: window.liveGapView._lastRow, handlerMs: window.lastHoverHandlerMs,
        }));
        hover.push({
          wallWithCdpMs: performance.now() - start, handlerMs: state.handlerMs,
          expectedSource: target.source, row: state.row,
        });
      }
      await page.evaluate(() => { window.liveGapPump = false; });
      await page.locator("#chart").screenshot({path: `${root}/${pattern}-${width}.png`});
      assert.deepEqual(errors, []);
      records.push({ pattern, width, startupMs, ...result, hover, errors });
      await page.close();
    }
  }
  await writeFile(output, JSON.stringify({
    started, ended: new Date().toISOString(),
    backend: "Chromium headless + ANGLE SwiftShader; DPR1; one chart per page",
    browserVersion: browser.version(), records,
    notes: [
      "CPU draw includes chrome/presentation; finish adds synchronous GL completion",
      "rAF intervals use a controlled redraw loop after warmup",
      "Hover wall includes Playwright/CDP roundtrip during redraw; handler is browser-only",
      "No hardware FPS or peak-memory claim",
    ],
  }, null, 2));
} finally {
  await browser.close();
  server.close();
}
