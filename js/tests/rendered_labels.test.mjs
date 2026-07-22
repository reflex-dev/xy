import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test, { after } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { chromium } from "playwright";
import { build as viteBuild } from "vite";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const BUNDLE = join(ROOT, "python", "xy", "static", "standalone.js");
const TICKS_SOURCE = join(ROOT, "js", "src", "30_ticks.ts");
const protocolSource = readFileSync(join(ROOT, "python", "xy", "config.py"), "utf8");
const protocolMatch = protocolSource.match(/^PROTOCOL_VERSION\s*=\s*(\d+)\s*$/m);
if (!protocolMatch) throw new Error("could not read PROTOCOL_VERSION from python/xy/config.py");
const PROTOCOL_VERSION = Number(protocolMatch[1]);

const evidencePath = process.env.XY_LABEL_EVIDENCE;
const evidence = {
  schema: "xy-rendered-label-oracle/v1",
  status: "started",
  contexts: [],
  negative_controls: {},
};
function writeEvidence() {
  if (evidencePath) writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`);
}
writeEvidence();

// Unit-test the authored formatter module, not a test rewrite of it. Vite is a
// pinned package dependency and this temporary ESM bundle is never shipped.
const compileDir = mkdtempSync(join(tmpdir(), "xy-label-formatters-"));
const compiledTicks = join(compileDir, "30_ticks.mjs");
process.on("exit", () => rmSync(compileDir, { recursive: true, force: true }));
let ticks;
try {
  await viteBuild({
    configFile: false,
    logLevel: "silent",
    build: {
      outDir: compileDir,
      emptyOutDir: false,
      copyPublicDir: false,
      target: "es2022",
      minify: false,
      rollupOptions: {
        input: TICKS_SOURCE,
        preserveEntrySignatures: "strict",
        output: { format: "es", entryFileNames: "30_ticks.mjs" },
      },
    },
  });
  ticks = await import(pathToFileURL(compiledTicks).href);
} catch (error) {
  evidence.status = "failed";
  evidence.failures = { formatter_bootstrap: String(error?.stack || error) };
  writeEvidence();
  throw error;
}

let formatterUnitsPassed = false;
let browserOraclePassed = false;
const failures = {};
after(() => {
  if (!formatterUnitsPassed && !failures.formatter_units) {
    failures.formatter_units = "formatter unit test did not complete";
  }
  if (!browserOraclePassed && !failures.browser_oracle) {
    failures.browser_oracle = "browser DOM oracle did not complete";
  }
  evidence.status = formatterUnitsPassed && browserOraclePassed ? "passed" : "failed";
  if (Object.keys(failures).length) evidence.failures = failures;
  writeEvidence();
});

function requireLabel(labels, expected, surface) {
  assert.ok(
    labels.includes(expected),
    `${surface}: expected ${JSON.stringify(expected)} in ${JSON.stringify(labels)}`,
  );
}

test("formatter units implement the declared numeric, UTC, log, and category policy", () => {
  const grouped = (1234.5).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  assert.equal(ticks.fmtNumberSpec(12.5, ".2f"), "12.50");
  assert.equal(ticks.fmtNumberSpec(1234.5, ",.2f"), grouped);
  assert.equal(ticks.fmtNumberSpec(1234.5, "$,.2f"), `$${grouped}`);
  assert.equal(ticks.fmtNumberSpec(0.375, ".1%"), "37.5%");
  assert.equal(ticks.fmtNumberSpec(3.25, ".2f GiB"), "3.25 GiB");

  const instant = Date.UTC(2024, 0, 1, 0, 30, 5);
  assert.equal(
    ticks.fmtTimeSpec(instant, "%Y-%m-%d %H:%M:%S %b %B"),
    "2024-01-01 00:30:05 Jan January",
  );
  assert.equal(ticks.fmtAxis({ scale: "log", format: ".0f" }, 0.1, 0.1), "0.1");
  assert.equal(ticks.fmtAxis({ kind: "category", categories: ["alpha", "beta"] }, 1, 1), "beta");

  assert.throws(() => ticks.fmtNumberSpec(1.25, ".2q"), /unsupported numeric format/);
  assert.throws(() => ticks.fmtTimeSpec(instant, "%Y-%q"), /unsupported UTC time format/);
  assert.throws(
    () => ticks.fmtAxis({ kind: "time", format: ".2f" }, instant, 1_000),
    /unsupported UTC time format/,
  );
  assert.throws(
    () => ticks.fmtAxis({ kind: "linear", format: "%Y" }, 2024, 1),
    /unsupported numeric format/,
  );
  assert.throws(
    () => ticks.fmtAxis({ kind: "category", categories: ["alpha"], format: ".0f" }, 0, 1),
    /unsupported category-axis format/,
  );
  formatterUnitsPassed = true;
});

async function renderProbe(page, input) {
  return page.evaluate(async ({ protocol, input }) => {
    const targetId = input.targetId || "x";
    const target = { id: targetId, side: targetId.startsWith("y") ? "right" : "bottom", ...input.axis };
    const xAxis = targetId === "x"
      ? target
      : { id: "x", kind: "linear", range: [0, 1], tick_values: [0, 1] };
    const yAxis = targetId === "y"
      ? target
      : { id: "y", kind: "linear", range: [0, 1], tick_values: [0, 1], side: "left" };
    const axes = { x: xAxis, y: yAxis };
    if (targetId !== "x" && targetId !== "y") axes[targetId] = target;

    const range = target.range || [0, 1];
    const span = Number(range[1]) - Number(range[0]) || 1;
    const targetIsX = targetId.startsWith("x");
    const xMeta = targetIsX
      ? { byte_offset: 0, len: 2, offset: Number(range[0]), scale: span, kind: target.kind === "time" ? "time_ms" : "float" }
      : { byte_offset: 0, len: 2, offset: 0, scale: 1, kind: "float" };
    const yMeta = targetIsX
      ? { byte_offset: 8, len: 2, offset: 0, scale: 1, kind: "float" }
      : { byte_offset: 8, len: 2, offset: Number(range[0]), scale: span, kind: target.kind === "time" ? "time_ms" : "float" };
    const spec = {
      protocol,
      width: 720,
      height: 300,
      x_axis: xAxis,
      y_axis: yAxis,
      axes,
      traces: [{
        id: 0,
        kind: "scatter",
        name: "oracle",
        tier: "direct",
        n_points: 2,
        style: { opacity: 1 },
        x: 0,
        y: 1,
        x_axis: targetIsX ? targetId : "x",
        y_axis: targetIsX ? "y" : targetId,
        color: { mode: "constant", color: "#2563eb" },
        size: { mode: "constant", size: 8 },
      }],
      columns: [xMeta, yMeta],
      tooltip: input.tooltip,
      colorbar: input.colorbar,
      backend: "none",
    };
    const host = document.createElement("div");
    document.body.appendChild(host);
    let view = null;
    try {
      view = window.xy.renderStandalone(host, spec, new Float32Array([0, 1, 0, 1]).buffer);
      view._drawNow();
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      if (input.tooltipRow) {
        view._renderTooltip(input.tooltipRow, 24, 24, { announce: false });
      }
      const axisLabels = Array.from(
        host.querySelectorAll('[data-xy-label-kind="tick"]'),
      ).filter((node) => node.dataset.xyAxis === targetId).map((node) => node.textContent);
      const tooltipLines = Array.from(
        host.querySelector('[data-xy-slot="tooltip"]')?.childNodes || [],
      ).filter((node) => node.nodeType === Node.TEXT_NODE).map((node) => node.textContent);
      const colorbarLabels = Array.from(
        host.querySelectorAll('[data-xy-slot="colorbar_tick"]'),
      ).map((node) => node.textContent);
      const colorbarTitle = host.querySelector('[data-xy-slot="colorbar_title"]')?.textContent || null;
      return { axisLabels, tooltipLines, colorbarLabels, colorbarTitle };
    } finally {
      view?.destroy();
      host.remove();
    }
  }, { protocol: PROTOCOL_VERSION, input });
}

async function rawFormatFailure(page, input) {
  return page.evaluate(({ protocol, input }) => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    let view = null;
    const xAxis = input.axis || { id: "x", kind: "linear", range: [0, 1] };
    const spec = {
      protocol,
      width: 320,
      height: 200,
      x_axis: xAxis,
      y_axis: { id: "y", kind: "linear", range: [0, 1] },
      traces: [],
      columns: [],
      tooltip: input.tooltip,
      backend: "none",
    };
    try {
      view = window.xy.renderStandalone(host, spec, new ArrayBuffer(0));
      if (input.tooltipRow) {
        view._renderTooltip(input.tooltipRow, 24, 24, { announce: false });
      }
      return null;
    } catch (error) {
      return String(error?.message || error);
    } finally {
      view?.destroy();
      host.remove();
    }
  }, { protocol: PROTOCOL_VERSION, input });
}

test("real DOM labels are exact in two non-UTC locale/time-zone contexts", {
  timeout: 120_000,
}, async () => {
  let browser;
  let failure = null;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (error) {
    failure = `Chromium could not launch; run npx playwright install chromium\n${error}`;
    failures.browser_oracle = failure;
    throw new Error(failure);
  }
  try {
    const contexts = [
      { locale: "en-US", timezoneId: "America/Los_Angeles" },
      { locale: "de-DE", timezoneId: "Asia/Tokyo" },
    ];
    for (const options of contexts) {
      const context = await browser.newContext({
        ...options,
        viewport: { width: 900, height: 500 },
        deviceScaleFactor: 1,
      });
      const page = await context.newPage();
      const pageErrors = [];
      page.on("pageerror", (error) => pageErrors.push(String(error)));
      await page.setContent("<!doctype html><meta charset=utf-8><body></body>");
      await page.addScriptTag({ path: BUNDLE });

      const resolved = await page.evaluate(() => ({
        locale: Intl.NumberFormat().resolvedOptions().locale,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }));
      assert.equal(resolved.locale, options.locale);
      assert.equal(resolved.timezone, options.timezoneId);
      assert.notEqual(resolved.timezone, "UTC");
      const grouped = new Intl.NumberFormat(options.locale, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(1234.5);

      const numeric = await renderProbe(page, {
        axis: { kind: "linear", range: [12, 13], tick_values: [12.5], format: ".2f" },
      });
      const grouping = await renderProbe(page, {
        axis: { kind: "linear", range: [1234, 1235], tick_values: [1234.5], format: ",.2f" },
      });
      const currency = await renderProbe(page, {
        axis: { kind: "linear", range: [1234, 1235], tick_values: [1234.5], format: "$,.2f" },
      });
      const time = await renderProbe(page, {
        axis: {
          kind: "time",
          range: [Date.UTC(2024, 0, 1), Date.UTC(2024, 0, 1, 1)],
          tick_values: [Date.UTC(2024, 0, 1, 0, 30)],
          format: "%Y-%m-%d %H:%M %b %B",
        },
      });
      const log = await renderProbe(page, {
        axis: {
          kind: "linear",
          scale: "log",
          range: [0.1, 1000],
          tick_values: [0.1, 1, 10, 100, 1000],
          format: ".0f",
        },
      });
      const category = await renderProbe(page, {
        axis: {
          kind: "category",
          range: [0, 2],
          tick_values: [0, 1, 2],
          categories: ["alpha", "beta", "gamma"],
        },
      });
      const named = await renderProbe(page, {
        targetId: "y2",
        axis: {
          kind: "linear",
          side: "right",
          range: [0, 1],
          tick_values: [0.375],
          format: ".1%",
        },
      });
      const chrome = await renderProbe(page, {
        axis: { kind: "linear", range: [0, 1], tick_values: [0, 1] },
        tooltip: {
          fields: ["amount", "when"],
          format: { amount: "$,.2f", when: "%Y-%m-%d %H:%M" },
        },
        tooltipRow: {
          trace: 0,
          index: 0,
          amount: 1234.5,
          when: Date.UTC(2024, 0, 1, 0, 30),
          when_kind: "time_ms",
        },
        colorbar: {
          domain: [0, 1],
          ticks: [0, 0.125, 1],
          label: "intensity",
          orientation: "vertical",
        },
      });

      requireLabel(numeric.axisLabels, "12.50", "numeric axis");
      requireLabel(grouping.axisLabels, grouped, "grouped axis");
      requireLabel(currency.axisLabels, `$${grouped}`, "currency axis");
      requireLabel(time.axisLabels, "2024-01-01 00:30 Jan January", "UTC time axis");
      for (const label of ["0.1", "1", "10", "100", "1000"]) {
        requireLabel(log.axisLabels, label, "log axis");
      }
      for (const label of ["alpha", "beta", "gamma"]) {
        requireLabel(category.axisLabels, label, "category axis");
      }
      requireLabel(named.axisLabels, "37.5%", "named percent axis");
      requireLabel(chrome.tooltipLines, `amount: $${grouped}`, "tooltip currency");
      requireLabel(chrome.tooltipLines, "when: 2024-01-01 00:30", "tooltip UTC time");
      assert.deepEqual(chrome.colorbarLabels, ["0", "0.125", "1"]);
      assert.equal(chrome.colorbarTitle, "intensity");

      // Independent oracle mutation: replacing a real DOM label must make the
      // comparator fail, proving this lane is not merely checking render health.
      const corrupted = numeric.axisLabels.map((label) => label === "12.50" ? "WRONG" : label);
      assert.throws(() => requireLabel(corrupted, "12.50", "mutated DOM label"), /expected/);

      const brokenAxis = await rawFormatFailure(page, {
        axis: { id: "x", kind: "linear", range: [0, 1], format: ".2q" },
      });
      const brokenTooltip = await rawFormatFailure(page, {
        tooltip: { format: { x: "not-a-format" } },
      });
      const brokenTooltipMapping = await rawFormatFailure(page, {
        tooltip: { format: "not-a-mapping" },
      });
      const mismatchedAxis = await rawFormatFailure(page, {
        axis: { id: "x", kind: "time", range: [0, 1], format: ".2f" },
      });
      const mismatchedTooltip = await rawFormatFailure(page, {
        tooltip: { fields: ["when"], format: { when: ".2f" } },
        tooltipRow: {
          trace: 0,
          index: 0,
          when: Date.UTC(2024, 0, 1, 0, 30),
          when_kind: "time_ms",
        },
      });
      const nonfiniteTooltip = await rawFormatFailure(page, {
        tooltip: { fields: ["amount"], format: { amount: ".2f" } },
        tooltipRow: { trace: 0, index: 0, amount: Number.NaN },
      });
      assert.match(brokenAxis || "", /unsupported numeric format/);
      assert.match(brokenTooltip || "", /unsupported tooltip field x format/);
      assert.match(brokenTooltipMapping || "", /tooltip format must be an object/);
      assert.match(mismatchedAxis || "", /unsupported UTC time format/);
      assert.match(mismatchedTooltip || "", /unsupported UTC time format/);
      assert.match(nonfiniteTooltip || "", /requires a numeric or time value/);
      assert.deepEqual(pageErrors, []);

      evidence.contexts.push({
        requested: options,
        resolved,
        labels: { numeric, grouping, currency, time, log, category, named, chrome },
      });
      evidence.negative_controls = {
        raw_axis_rejection: brokenAxis,
        raw_tooltip_rejection: brokenTooltip,
        raw_tooltip_mapping_rejection: brokenTooltipMapping,
        raw_axis_kind_mismatch_rejection: mismatchedAxis,
        raw_tooltip_kind_mismatch_rejection: mismatchedTooltip,
        raw_tooltip_nonfinite_rejection: nonfiniteTooltip,
        corrupted_dom_oracle_rejected: true,
      };
      await context.close();
    }
    browserOraclePassed = true;
  } catch (error) {
    failure = String(error?.stack || error);
    failures.browser_oracle = failure;
    throw error;
  } finally {
    await browser.close();
  }
});
