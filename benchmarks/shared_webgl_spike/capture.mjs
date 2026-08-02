#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const require = createRequire(import.meta.url);
const HARNESS_DIRECTORY = path.dirname(fileURLToPath(import.meta.url));
const HARNESS_FILES = ["index.html", "experiment.js", "styles.css"];
const CAPTURE_CHART_COUNT = 50;
const SNAPSHOT_DEADLINE_MS = 10_000;
const VERIFY_DEADLINE_MS = 30_000;
const CYCLE_DEADLINE_MS = 60_000;
const BENCHMARK_OVERHEAD_DEADLINE_MS = 30_000;
const HARNESS_FETCH_DEADLINE_MS = 10_000;
const CLEANUP_DEADLINE_MS = 5_000;
const EXPECTED_NATIVE_CONTEXT_LIMIT_WARNING =
  /^(?:WARNING:\s*)?Too many active WebGL contexts\. Oldest context will be lost\.$/;
const EXPECTED_SHARED_CANVAS_READBACK_WARNING =
  "Canvas2D: Multiple readback operations using getImageData are faster with the " +
  "willReadFrequently attribute set to true. See: " +
  "https://html.spec.whatwg.org/multipage/canvas.html#concept-canvas-will-read-frequently";
const DIAGNOSTIC_ALLOWLIST_CAPS = {
  "expected-native-webgl-context-limit": CAPTURE_CHART_COUNT,
  "expected-shared-canvas-readback": CAPTURE_CHART_COUNT,
};

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
  if (values.length === 0) throw new Error("cannot aggregate an empty value set");
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
}

function medianAt(runs, read) {
  return median(runs.map(read));
}

function integerMedian(values) {
  if (values.length === 0) throw new Error("cannot aggregate an empty count set");
  if (!values.every(Number.isInteger)) {
    throw new Error(`count aggregation requires integers, received ${JSON.stringify(values)}`);
  }
  const ordered = [...values].sort((left, right) => left - right);
  // For an even number of successful attempts, use the lower observed middle
  // value rather than averaging two counts into a fractional result.
  return ordered[Math.floor((ordered.length - 1) / 2)];
}

function integerMedianAt(runs, read) {
  return integerMedian(runs.map(read));
}

function uniformAt(runs, read, label) {
  const values = runs.map(read);
  const encoded = values.map((value) => JSON.stringify(value));
  if (!encoded.every((value) => value === encoded[0])) {
    throw new Error(`${label} must be identical across successful attempts`);
  }
  return values[0];
}

function commandOutput(command, args) {
  return execFileSync(command, args, { encoding: "utf8" }).trim();
}

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function harnessUrl(baseUrl, fileName) {
  return new URL(fileName, baseUrl).href;
}

async function fetchBytesWithDeadline(url) {
  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(new Error(`fetch exceeded ${HARNESS_FETCH_DEADLINE_MS} ms`)),
    HARNESS_FETCH_DEADLINE_MS,
  );
  try {
    const response = await fetch(url, { cache: "no-store", signal: controller.signal });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} ${response.statusText}`);
    }
    return Buffer.from(await response.arrayBuffer());
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error(
        `could not fingerprint ${url}: exceeded the ${HARNESS_FETCH_DEADLINE_MS} ms deadline`,
        { cause: error },
      );
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function verifyServedHarness(baseUrl, expectedFingerprints = null) {
  const files = {};
  for (const fileName of HARNESS_FILES) {
    const localBytes = await readFile(path.join(HARNESS_DIRECTORY, fileName));
    const localSha256 = sha256(localBytes);
    if (
      expectedFingerprints &&
      expectedFingerprints.files[fileName]?.sha256 !== localSha256
    ) {
      throw new Error(`${fileName} changed after the capture preflight fingerprint`);
    }

    let servedBytes;
    try {
      servedBytes = await fetchBytesWithDeadline(harnessUrl(baseUrl, fileName));
    } catch (error) {
      throw new Error(`could not fingerprint served ${fileName}: ${error.message}`, {
        cause: error,
      });
    }
    const servedSha256 = sha256(servedBytes);
    if (servedSha256 !== localSha256) {
      throw new Error(
        `served ${fileName} does not match the local checkout ` +
          `(local ${localSha256}, served ${servedSha256})`,
      );
    }
    files[fileName] = { sha256: localSha256 };
  }
  return { algorithm: "sha256", files };
}

function responseMatchesHarnessFile(response, baseUrl, fileName) {
  try {
    const actual = new URL(response.url());
    const expected = new URL(harnessUrl(baseUrl, fileName));
    return actual.origin === expected.origin && actual.pathname === expected.pathname;
  } catch {
    return false;
  }
}

async function verifyBrowserHarnessResponses(responses, runner) {
  for (const fileName of HARNESS_FILES) {
    const response = responses.get(fileName);
    if (!response) throw new Error(`browser did not load the fingerprinted ${fileName}`);
    if (!response.ok()) {
      throw new Error(
        `browser load of ${fileName} failed: HTTP ${response.status()} ${response.statusText()}`,
      );
    }
    const actualSha256 = sha256(await response.body());
    const expectedSha256 = runner.harness.files[fileName].sha256;
    if (actualSha256 !== expectedSha256) {
      throw new Error(
        `browser-loaded ${fileName} does not match the preflight fingerprint ` +
          `(expected ${expectedSha256}, received ${actualSha256})`,
      );
    }
  }
}

async function runnerEnvironment(baseUrl) {
  const status = commandOutput("git", ["status", "--porcelain"]);
  if (status) throw new Error("capture requires a clean git worktree");
  const python = JSON.parse(
    commandOutput("python3.12", [
      "-c",
      "import json,platform;print(json.dumps({'version':platform.python_version()," +
        "'implementation':platform.python_implementation(),'compiler':platform.python_compiler()}))",
    ]),
  );
  // Only associate the capture with the local revision after the server has
  // proven that it is serving byte-identical harness assets from this checkout.
  const harness = await verifyServedHarness(baseUrl);
  if (commandOutput("git", ["status", "--porcelain"])) {
    throw new Error("capture worktree changed during harness fingerprint verification");
  }
  return {
    node: process.version,
    playwright: require("playwright/package.json").version,
    python,
    platform: { name: process.platform, arch: process.arch },
    harness,
    git: {
      commit: commandOutput("git", ["rev-parse", "HEAD"]),
      branch: commandOutput("git", ["branch", "--show-current"]),
      dirty: false,
    },
  };
}

function withDeadline(label, timeoutMs, operation, onTimeout = null) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => {
      if (onTimeout) Promise.resolve().then(onTimeout).catch(() => {});
      reject(new Error(`${label} exceeded the ${timeoutMs} ms Node-side deadline`));
    }, timeoutMs);
  });
  return Promise.race([Promise.resolve().then(operation), deadline]).finally(() => {
    clearTimeout(timer);
  });
}

async function boundedCleanup(label, operation) {
  try {
    await withDeadline(label, CLEANUP_DEADLINE_MS, operation);
    return null;
  } catch (error) {
    return new Error(`${label} failed: ${error.message}`, { cause: error });
  }
}

function sanitizedBrowserVersion(browser) {
  try {
    const value = browser.version();
    if (typeof value !== "string" || value.length === 0) return null;
    return value.replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 200);
  } catch {
    return null;
  }
}

function redact(value, redactions) {
  let result = String(value ?? "");
  for (const { value: secret, replacement } of redactions) {
    if (secret) result = result.replaceAll(secret, replacement);
  }
  return result;
}

function serializedError(error, redactions) {
  return {
    name: redact(error?.name || "Error", redactions),
    message: redact(error?.message || error, redactions),
    stack: redact(error?.stack || "", redactions),
  };
}

function outputJson(value, redactions) {
  return `${JSON.stringify(
    value,
    (_key, candidate) =>
      typeof candidate === "string" ? redact(candidate, redactions) : candidate,
    2,
  )}\n`;
}

function urlMatchesHarnessFile(url, baseUrl, fileName) {
  try {
    const actual = new URL(url);
    const expected = new URL(harnessUrl(baseUrl, fileName));
    return actual.origin === expected.origin && actual.pathname === expected.pathname;
  } catch {
    return false;
  }
}

function consoleDiagnostic(mode, phase, baseUrl, allowlistCounts, message) {
  const level = message.type();
  const text = message.text();
  const location = message.location();
  let classification = "unexpected";
  if (
    mode === "native" &&
    phase === "initialization" &&
    level === "warning" &&
    urlMatchesHarnessFile(location.url, baseUrl, "experiment.js") &&
    EXPECTED_NATIVE_CONTEXT_LIMIT_WARNING.test(text)
  ) {
    classification = "expected-native-webgl-context-limit";
  } else if (
    mode === "shared" &&
    phase === "verify" &&
    level === "warning" &&
    urlMatchesHarnessFile(location.url, baseUrl, "experiment.js") &&
    text === EXPECTED_SHARED_CANVAS_READBACK_WARNING
  ) {
    classification = "expected-shared-canvas-readback";
  }
  const occurrence =
    classification === "unexpected"
      ? null
      : (allowlistCounts[classification] = (allowlistCounts[classification] || 0) + 1);
  const cap = DIAGNOSTIC_ALLOWLIST_CAPS[classification] ?? 0;
  return {
    source: "console",
    phase,
    level,
    text,
    location,
    allowed: occurrence !== null && occurrence <= cap,
    classification,
    occurrence,
    allowlistCap: occurrence === null ? null : cap,
  };
}

function pageErrorDiagnostic(phase, error) {
  return {
    source: "pageerror",
    phase,
    level: "error",
    text: String(error?.message || error),
    stack: String(error?.stack || ""),
    allowed: false,
    classification: "unexpected",
  };
}

function captureError(message, attempt) {
  const error = new Error(message);
  error.captureAttempt = attempt;
  return error;
}

function summarizeProfile(runs, mode) {
  const first = runs[0];
  const requestedCharts = uniformAt(
    runs,
    (run) => run.benchmark.requestedCharts,
    `${mode} requested chart count`,
  );
  const liveCharts = uniformAt(
    runs,
    (run) => run.benchmark.liveCharts,
    `${mode} live chart count`,
  );
  const liveContexts = uniformAt(
    runs,
    (run) => run.benchmark.liveContexts,
    `${mode} live context count`,
  );
  const fullyLive = liveCharts === requestedCharts;
  for (const [label, read] of [
    ["requested duration", (run) => run.benchmark.requestedDurationMs],
    ["target fps", (run) => run.benchmark.targetFps],
    ["points per chart", (run) => run.benchmark.pointsPerChart],
    ["dense mode", (run) => run.benchmark.dense],
    ["benchmark state stress", (run) => run.benchmark.stateStress],
    ["device pixel ratio", (run) => run.benchmark.dpr],
    ["canvas pixel range", (run) => run.benchmark.canvasPixels],
    ["viewport", (run) => run.benchmark.viewportCssPixels],
    ["browser environment", (run) => run.benchmark.environment],
  ]) {
    uniformAt(runs, read, `${mode} ${label}`);
  }
  if (mode === "native") {
    uniformAt(
      runs,
      (run) => run.initialSnapshot.stats.createdContexts,
      "native created context count",
    );
  }
  for (const run of runs) {
    const rawFullyLive = run.benchmark.liveCharts === run.benchmark.requestedCharts;
    const renderingChecksPass =
      run.correctness.stateStress === true &&
      run.correctness.canaryChecks === run.benchmark.liveCharts &&
      run.correctness.canaryFailures.length === 0 &&
      run.correctness.pickChecks === run.benchmark.liveCharts * 3 &&
      run.correctness.pickFailures.length === 0;
    if (!renderingChecksPass) {
      throw new Error(`${mode} has a failed or incomplete correctness check`);
    }
    if (
      run.benchmark.fullyLive !== rawFullyLive ||
      run.correctness.pass !== rawFullyLive
    ) {
      throw new Error(`${mode} has inconsistent chart availability or correctness telemetry`);
    }
    if (
      run.benchmark.contextLossesDuringRun !== 0 ||
      run.benchmark.contextRestoresDuringRun !== 0
    ) {
      throw new Error(`${mode} changed WebGL context state during a governed benchmark run`);
    }
    if (!run.recovery.correctnessAfterRestore) {
      throw new Error(`${mode} recovery did not pass in every successful attempt`);
    }
    if (mode === "shared") {
      if (!rawFullyLive || run.benchmark.liveContexts !== 1) {
        throw new Error("shared mode did not preserve its chart/context invariant");
      }
      if (
        run.recovery.contextLosses !== 1 ||
        run.recovery.contextRestores !== 1 ||
        run.recovery.expectedCharts !== run.benchmark.requestedCharts ||
        run.recovery.liveChartsAfterRestore !== run.recovery.expectedCharts
      ) {
        throw new Error("shared mode recovery telemetry is inconsistent");
      }
    } else {
      if (run.benchmark.liveContexts !== run.benchmark.liveCharts) {
        throw new Error("native live context and chart counts differ");
      }
      if (
        run.recovery.contextLosses === 0 ||
        run.recovery.contextRestores === 0 ||
        run.recovery.expectedCharts !== run.benchmark.liveCharts ||
        run.recovery.liveChartsAfterRestore < run.recovery.expectedCharts
      ) {
        throw new Error("native mode recovery telemetry is inconsistent");
      }
    }
  }
  const durationMs = medianAt(runs, (run) => run.benchmark.durationMs);
  const productiveBatches = integerMedianAt(
    runs,
    (run) => run.benchmark.productiveBatches,
  );
  const targetFps = first.benchmark.targetFps;
  const expectedBatches = Math.floor((durationMs * targetFps) / 1000);
  if (
    !runs.every(
      (run) =>
        run.benchmark.chartPresentations ===
          run.benchmark.productiveBatches * run.benchmark.liveCharts,
    )
  ) {
    throw new Error(`${mode} raw presentation counts are not count-conserving`);
  }
  const chartPresentations = productiveBatches * liveCharts;
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
    contextLossesDuringRun: 0,
    contextRestoresDuringRun: 0,
  };
  if (mode === "shared") {
    benchmark.presentMsPerChart = {
      p50: medianAt(runs, (run) => run.benchmark.presentMsPerChart.p50),
      p95: medianAt(runs, (run) => run.benchmark.presentMsPerChart.p95),
    };
  }
  return {
    requestedCharts,
    liveCharts,
    liveContexts,
    createdContexts:
      mode === "native"
        ? integerMedianAt(runs, (run) => run.initialSnapshot.stats.createdContexts)
        : undefined,
    fullyLive,
    correctness: {
      pass: fullyLive,
      canaryChecks: liveCharts,
      canaryFailures: 0,
      pickChecks: liveCharts * 3,
      pickFailures: 0,
      cropOffsetPixels: integerMedianAt(runs, (run) => run.correctness.cropOffsetPixels),
      stateStress: runs.every((run) => run.correctness.stateStress),
      timestamps: runs.map((run) => run.correctness.timestamp),
    },
    recovery: {
      contextLosses: integerMedianAt(runs, (run) => run.recovery.contextLosses),
      contextRestores: integerMedianAt(runs, (run) => run.recovery.contextRestores),
      expectedCharts: integerMedianAt(runs, (run) => run.recovery.expectedCharts),
      liveChartsAfterRestore: integerMedianAt(
        runs,
        (run) => run.recovery.liveChartsAfterRestore,
      ),
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
  const diagnostics = [];
  const allowlistCounts = {};
  let phase = "preflight";
  const attempt = {
    schemaVersion: 1,
    kind: "shared-webgl-spike-raw",
    capturedAtUtc: new Date().toISOString(),
    mode,
    repetition,
    runnerEnvironment: runner,
    browserVersion: null,
    diagnostics,
  };
  const launchOptions = { headless: true };
  if (options.chromium) launchOptions.executablePath = options.chromium;
  let browser;
  let context;
  let operationError = null;
  try {
    await verifyServedHarness(options.baseUrl, runner.harness);
    phase = "initialization";
    browser = await chromium.launch(launchOptions);
    attempt.browserVersion = sanitizedBrowserVersion(browser);
    context = await browser.newContext({
      viewport: { width: options.viewportWidth, height: options.viewportHeight },
    });
    const page = await context.newPage();
    const browserResponses = new Map();
    page.on("response", (response) => {
      for (const fileName of HARNESS_FILES) {
        if (responseMatchesHarnessFile(response, options.baseUrl, fileName)) {
          browserResponses.set(fileName, response);
        }
      }
    });
    page.on("pageerror", (error) =>
      diagnostics.push(pageErrorDiagnostic(phase, error)),
    );
    page.on("console", (message) => {
      if (["warning", "error"].includes(message.type())) {
        diagnostics.push(
          consoleDiagnostic(
            mode,
            phase,
            options.baseUrl,
            allowlistCounts,
            message,
          ),
        );
      }
    });
    const cancelEvaluation = () => context.close();
    const url = new URL("index.html", options.baseUrl);
    url.searchParams.set("mode", mode);
    url.searchParams.set("count", String(CAPTURE_CHART_COUNT));
    await page.goto(url.href, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.waitForFunction(() => window.__EXPERIMENT_READY === true, undefined, {
      timeout: 30_000,
    });
    await page.waitForTimeout(1_000);
    await withDeadline(
      "browser harness response verification",
      HARNESS_FETCH_DEADLINE_MS,
      () => verifyBrowserHarnessResponses(browserResponses, runner),
      cancelEvaluation,
    );
    phase = "snapshot";
    const initialSnapshot = await withDeadline(
      "initial snapshot()",
      SNAPSHOT_DEADLINE_MS,
      () => page.evaluate(() => window.__sharedWebglExperiment.snapshot()),
      cancelEvaluation,
    );
    phase = "verify";
    const correctness = await withDeadline(
      "verify()",
      VERIFY_DEADLINE_MS,
      () => page.evaluate(() => window.__sharedWebglExperiment.verify()),
      cancelEvaluation,
    );
    await page.waitForTimeout(50);
    phase = "benchmark";
    const benchmark = await withDeadline(
      "benchmark()",
      options.durationMs + BENCHMARK_OVERHEAD_DEADLINE_MS,
      () =>
        page.evaluate(
          (durationMs) => window.__sharedWebglExperiment.benchmark(durationMs),
          options.durationMs,
        ),
      cancelEvaluation,
    );
    phase = "pre-recovery-snapshot";
    const preRecovery = await withDeadline(
      "pre-recovery snapshot()",
      SNAPSHOT_DEADLINE_MS,
      () => page.evaluate(() => window.__sharedWebglExperiment.snapshot()),
      cancelEvaluation,
    );
    phase = "cycle";
    const cycleResult = await withDeadline(
      "cycleContext()",
      CYCLE_DEADLINE_MS,
      () => page.evaluate(() => window.__sharedWebglExperiment.cycleContext()),
      cancelEvaluation,
    );
    await page.waitForTimeout(50);
    phase = "post-recovery-snapshot";
    const postRecovery = await withDeadline(
      "post-recovery snapshot()",
      SNAPSHOT_DEADLINE_MS,
      () => page.evaluate(() => window.__sharedWebglExperiment.snapshot()),
      cancelEvaluation,
    );
    Object.assign(attempt, {
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
    });
  } catch (error) {
    operationError = error;
  } finally {
    phase = "teardown";
    const cleanupErrors = [];
    if (context) {
      const error = await boundedCleanup("browser context close", () => context.close());
      if (error) cleanupErrors.push(error);
    }
    if (browser) {
      const error = await boundedCleanup("browser close", () => browser.close());
      if (error) cleanupErrors.push(error);
    }
    if (cleanupErrors.length > 0) {
      attempt.cleanupErrors = cleanupErrors.map((error) => ({
        name: error.name,
        message: error.message,
        stack: error.stack,
      }));
      operationError ||= new AggregateError(cleanupErrors, "browser cleanup failed");
    }
  }
  attempt.diagnostics = diagnostics.map((diagnostic) => ({ ...diagnostic }));
  const unexpected = attempt.diagnostics.filter((diagnostic) => !diagnostic.allowed);
  if (!operationError && unexpected.length > 0) {
    operationError = captureError(
      `${unexpected.length} unexpected page diagnostic(s) were captured`,
      attempt,
    );
  }
  if (operationError) {
    operationError.captureAttempt ??= attempt;
    throw operationError;
  }
  return attempt;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const runner = await runnerEnvironment(options.baseUrl);
  await mkdir(options.outputDir, { recursive: true });
  const results = { shared: [], native: [] };
  const rawFiles = { shared: [], native: [] };
  const attemptedRawFiles = { shared: [], native: [] };
  const failures = [];
  const captureOrder = [];
  const redactions = [
    { value: options.chromium, replacement: "<chromium-executable>" },
    { value: path.resolve(options.outputDir), replacement: "<output-directory>" },
    { value: HARNESS_DIRECTORY, replacement: "<harness-directory>" },
    { value: process.cwd(), replacement: "<working-directory>" },
    { value: homedir(), replacement: "<home-directory>" },
  ]
    .filter(({ value }) => value)
    .sort((left, right) => right.value.length - left.value.length);
  for (let repetition = 1; repetition <= options.repetitions; repetition += 1) {
    const modes = repetition % 2 === 1 ? ["shared", "native"] : ["native", "shared"];
    captureOrder.push({ repetition, modes });
    for (const mode of modes) {
      const stem = `run-${String(repetition).padStart(2, "0")}-${mode}`;
      const file = path.join(options.outputDir, `${stem}.json`);
      const recordedFile = path.basename(file);
      let result = null;
      try {
        result = await captureProfile(options, runner, mode, repetition);
        await writeFile(file, outputJson(result, redactions), "utf8");
        attemptedRawFiles[mode].push(recordedFile);
        results[mode].push(result);
        rawFiles[mode].push(recordedFile);
        console.log(`captured ${stem}`);
      } catch (error) {
        error.captureAttempt ??= result;
        const failure = {
          ...(error.captureAttempt || {
            schemaVersion: 1,
            kind: "shared-webgl-spike-raw",
            capturedAtUtc: new Date().toISOString(),
            mode,
            repetition,
            runnerEnvironment: runner,
            browserVersion: null,
            diagnostics: [],
          }),
          succeeded: false,
          error: serializedError(error, redactions),
        };
        await writeFile(file, outputJson(failure, redactions), "utf8");
        attemptedRawFiles[mode].push(recordedFile);
        failures.push({
          mode,
          repetition,
          file: recordedFile,
          error: failure.error,
          diagnosticCount: failure.diagnostics.length,
        });
        console.error(`failed ${stem}: ${redact(error.message, redactions)}`);
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
    captureOrder,
    runnerEnvironment: runner,
    captureConfiguration: {
      baseUrl: options.baseUrl,
      browserExecutable: options.chromium
        ? "explicit executable (absolute path redacted)"
        : "playwright default",
      viewportWidth: options.viewportWidth,
      viewportHeight: options.viewportHeight,
    },
    attemptedRawFiles,
    rawFiles,
    browserVersions: Object.fromEntries(
      ["shared", "native"].map((mode) => [
        mode,
        [...new Set(results[mode].map((result) => result.browserVersion).filter(Boolean))],
      ]),
    ),
    failures,
    profiles: {},
  };
  for (const mode of ["shared", "native"]) {
    if (results[mode].length === options.repetitions) {
      try {
        summary.profiles[mode] = summarizeProfile(results[mode], mode);
      } catch (error) {
        failures.push({
          mode,
          stage: "aggregation",
          error: serializedError(error, redactions),
        });
      }
    }
  }
  const summaryPath = path.join(options.outputDir, "summary-input.json");
  await writeFile(summaryPath, outputJson(summary, redactions), "utf8");
  console.log(`wrote ${path.basename(summaryPath)}`);
  if (failures.length || !summary.profiles.shared || !summary.profiles.native) process.exitCode = 1;
}

await main();
