#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";

const require = createRequire(import.meta.url);

function parseArgs(argv) {
  const options = {
    baseUrl: "http://127.0.0.1:4173/",
    chromium: undefined,
    durationMs: 3000,
    outputDir: "benchmarks/shared_webgl_spike/results/raw",
    repetitions: 3,
    viewportHeight: 720,
    viewportWidth: 1280,
  };
  const valueOptions = new Map([
    ["--base-url", "baseUrl"],
    ["--chromium", "chromium"],
    ["--duration-ms", "durationMs"],
    ["--output-dir", "outputDir"],
    ["--repetitions", "repetitions"],
    ["--viewport-height", "viewportHeight"],
    ["--viewport-width", "viewportWidth"],
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const option = argv[index];
    if (option === "--help") {
      console.log(
        "Usage: node capture.mjs [--base-url URL] [--chromium PATH] " +
          "[--duration-ms N] [--output-dir DIR] [--repetitions N] " +
          "[--viewport-width N] [--viewport-height N]",
      );
      process.exit(0);
    }
    const key = valueOptions.get(option);
    if (!key || index + 1 >= argv.length) throw new Error(`Unknown or incomplete option: ${option}`);
    const value = argv[(index += 1)];
    options[key] = key === "baseUrl" || key === "chromium" || key === "outputDir" ? value : Number(value);
  }
  for (const key of ["durationMs", "repetitions", "viewportHeight", "viewportWidth"]) {
    if (!Number.isInteger(options[key]) || options[key] <= 0) {
      throw new Error(`${key} must be a positive integer`);
    }
  }
  if (options.repetitions < 3) throw new Error("repetitions must be at least 3");
  return options;
}

function median(values) {
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
}

function medianAt(runs, read) {
  return median(runs.map(read));
}

function commandOutput(command, args) {
  return execFileSync(command, args, { encoding: "utf8" }).trim();
}

function runnerEnvironment() {
  const status = commandOutput("git", ["status", "--porcelain"]);
  if (status) throw new Error("capture requires a clean git worktree");
  const python = JSON.parse(
    commandOutput("python3.12", [
      "-c",
      "import json,platform;print(json.dumps({'version':platform.python_version()," +
        "'implementation':platform.python_implementation(),'compiler':platform.python_compiler()}))",
    ]),
  );
  return {
    node: process.version,
    playwright: require("playwright/package.json").version,
    python,
    platform: { name: process.platform, arch: process.arch },
    git: {
      commit: commandOutput("git", ["rev-parse", "HEAD"]),
      branch: commandOutput("git", ["branch", "--show-current"]),
      dirty: false,
    },
  };
}

function summarizeProfile(runs, mode) {
  const first = runs[0];
  const durationMs = medianAt(runs, (run) => run.benchmark.durationMs);
  const productiveBatches = medianAt(runs, (run) => run.benchmark.productiveBatches);
  const targetFps = first.benchmark.targetFps;
  const expectedBatches = Math.floor((durationMs * targetFps) / 1000);
  const chartPresentations = medianAt(runs, (run) => run.benchmark.chartPresentations);
  const benchmark = {
    requestedDurationMs: first.benchmark.requestedDurationMs,
    durationMs,
    pointsPerChart: first.benchmark.pointsPerChart,
    dense: first.benchmark.dense,
    targetFps,
    observedFps: (productiveBatches * 1000) / Math.max(1, durationMs),
    productiveBatches,
    expectedBatches,
    droppedIntervals: Math.max(0, expectedBatches - productiveBatches),
    chartPresentations,
    chartPresentationsPerSecond: (chartPresentations * 1000) / Math.max(1, durationMs),
    frameMs: {
      p50: medianAt(runs, (run) => run.benchmark.frameMs.p50),
      p95: medianAt(runs, (run) => run.benchmark.frameMs.p95),
      p99: medianAt(runs, (run) => run.benchmark.frameMs.p99),
    },
    stateStress: first.benchmark.stateStress,
    contextLossesDuringRun: medianAt(runs, (run) => run.benchmark.contextLossesDuringRun),
    contextRestoresDuringRun: medianAt(runs, (run) => run.benchmark.contextRestoresDuringRun),
  };
  if (mode === "shared") {
    benchmark.presentMsPerChart = {
      p50: medianAt(runs, (run) => run.benchmark.presentMsPerChart.p50),
      p95: medianAt(runs, (run) => run.benchmark.presentMsPerChart.p95),
    };
  }
  return {
    requestedCharts: medianAt(runs, (run) => run.benchmark.requestedCharts),
    liveCharts: medianAt(runs, (run) => run.benchmark.liveCharts),
    liveContexts: medianAt(runs, (run) => run.benchmark.liveContexts),
    createdContexts:
      mode === "native"
        ? medianAt(runs, (run) => run.initialSnapshot.stats.createdContexts)
        : undefined,
    fullyLive: runs.every((run) => run.benchmark.fullyLive),
    correctness: {
      pass: runs.every((run) => run.correctness.pass),
      canaryChecks: medianAt(runs, (run) => run.correctness.canaryChecks),
      canaryFailures: medianAt(runs, (run) => run.correctness.canaryFailures.length),
      pickChecks: medianAt(runs, (run) => run.correctness.pickChecks),
      pickFailures: medianAt(runs, (run) => run.correctness.pickFailures.length),
      cropOffsetPixels: medianAt(runs, (run) => run.correctness.cropOffsetPixels),
      stateStress: runs.every((run) => run.correctness.stateStress),
      timestamps: runs.map((run) => run.correctness.timestamp),
    },
    recovery: {
      contextLosses: medianAt(runs, (run) => run.recovery.contextLosses),
      contextRestores: medianAt(runs, (run) => run.recovery.contextRestores),
      expectedCharts: medianAt(runs, (run) => run.recovery.expectedCharts),
      liveChartsAfterRestore: medianAt(runs, (run) => run.recovery.liveChartsAfterRestore),
      correctnessAfterRestore: runs.every((run) => run.recovery.correctnessAfterRestore),
      visibleFramesDuringLossChecked: false,
    },
    benchmark,
    environment: first.benchmark.environment,
    dpr: first.benchmark.dpr,
    canvasPixels: first.benchmark.canvasPixels,
    viewportCssPixels: first.benchmark.viewportCssPixels,
  };
}

async function captureProfile(options, runner, mode, repetition) {
  const launchOptions = { headless: true };
  if (options.chromium) launchOptions.executablePath = options.chromium;
  const browser = await chromium.launch(launchOptions);
  try {
    const context = await browser.newContext({
      viewport: { width: options.viewportWidth, height: options.viewportHeight },
    });
    const page = await context.newPage();
    const url = new URL(options.baseUrl);
    url.searchParams.set("mode", mode);
    url.searchParams.set("count", "50");
    await page.goto(url.href, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => window.__EXPERIMENT_READY === true, undefined, {
      timeout: 30_000,
    });
    await page.waitForTimeout(1_000);
    const initialSnapshot = await page.evaluate(() => window.__sharedWebglExperiment.snapshot());
    const correctness = await page.evaluate(() => window.__sharedWebglExperiment.verify());
    const benchmark = await page.evaluate(
      (durationMs) => window.__sharedWebglExperiment.benchmark(durationMs),
      options.durationMs,
    );
    const preRecovery = await page.evaluate(() => window.__sharedWebglExperiment.snapshot());
    const cycleResult = await page.evaluate(() => window.__sharedWebglExperiment.cycleContext());
    const postRecovery = await page.evaluate(() => window.__sharedWebglExperiment.snapshot());
    const browserVersion = browser.version();
    await context.close();
    return {
      schemaVersion: 1,
      kind: "shared-webgl-spike-raw",
      capturedAtUtc: new Date().toISOString(),
      mode,
      repetition,
      runnerEnvironment: runner,
      browserVersion,
      initialSnapshot,
      correctness,
      benchmark,
      preRecovery,
      cycleResult,
      postRecovery,
      recovery: {
        contextLosses: postRecovery.contextLosses - preRecovery.contextLosses,
        contextRestores: postRecovery.contextRestores - preRecovery.contextRestores,
        expectedCharts: postRecovery.lastCheck?.expectedCharts ?? 0,
        liveChartsAfterRestore: postRecovery.stats?.liveCharts ?? 0,
        correctnessAfterRestore: Boolean(postRecovery.lastCheck?.pass && cycleResult),
        visibleFramesDuringLossChecked: false,
      },
    };
  } finally {
    await browser.close();
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const runner = runnerEnvironment();
  await mkdir(options.outputDir, { recursive: true });
  const results = { shared: [], native: [] };
  const rawFiles = { shared: [], native: [] };
  const failures = [];
  for (let repetition = 1; repetition <= options.repetitions; repetition += 1) {
    for (const mode of ["shared", "native"]) {
      const stem = `run-${String(repetition).padStart(2, "0")}-${mode}`;
      const file = path.join(options.outputDir, `${stem}.json`);
      try {
        const result = await captureProfile(options, runner, mode, repetition);
        results[mode].push(result);
        rawFiles[mode].push(file);
        await writeFile(file, `${JSON.stringify(result, null, 2)}\n`, "utf8");
        console.log(`captured ${stem}`);
      } catch (error) {
        const failure = {
          schemaVersion: 1,
          kind: "shared-webgl-spike-raw",
          capturedAtUtc: new Date().toISOString(),
          mode,
          repetition,
          error: { message: error.message, stack: error.stack },
        };
        failures.push(failure);
        await writeFile(file, `${JSON.stringify(failure, null, 2)}\n`, "utf8");
        console.error(`failed ${stem}: ${error.message}`);
      }
    }
  }
  const summary = {
    schemaVersion: 1,
    kind: "shared-webgl-spike-capture-set",
    generatedAtUtc: new Date().toISOString(),
    repetitionsRequested: options.repetitions,
    requestedDurationMs: options.durationMs,
    coldBrowserProcessPerProfile: true,
    runnerEnvironment: runner,
    captureConfiguration: {
      baseUrl: options.baseUrl,
      chromium: options.chromium ?? "playwright default",
      viewportWidth: options.viewportWidth,
      viewportHeight: options.viewportHeight,
    },
    rawFiles,
    failures,
    profiles: {},
  };
  for (const mode of ["shared", "native"]) {
    if (results[mode].length >= 3) summary.profiles[mode] = summarizeProfile(results[mode], mode);
  }
  const summaryPath = path.join(options.outputDir, "summary-input.json");
  await writeFile(summaryPath, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
  console.log(`wrote ${summaryPath}`);
  if (failures.length || !summary.profiles.shared || !summary.profiles.native) process.exitCode = 1;
}

await main();
