#!/usr/bin/env node
// Dependency-free "bundler": the client is hand-written ES-module source split
// into ordered parts under src/ (plain script content; exports live only in the
// final part). Building = concatenating them (anywidget ESM) and wrapping the
// export-free body (standalone IIFE for static HTML export). No npm, no
// registry, no supply chain — deliberate (§33).
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Concatenation order is load-bearing (const/class definitions before use).
const PARTS = [
  "00_header.js", //     doc header, "use strict", PROTOCOL version
  "10_colormaps.js", //  colormap stops + LUT builder (§36 CVD-safe defaults)
  "20_theme.js", //      CSS color resolution + --chart-* tokens (§36)
  "30_ticks.js", //      f64 tick/format math — never through f32 (§16)
  "40_gl.js", //         GL helpers + all shaders (marks, pick, density, line)
  "45_lod.js", //        chart-agnostic tier LOD: drill lifecycle, fades, cache (§5/§28)
  "50_chartview.js", //  ChartView: render, interaction, kernel comm
  "55_marks.js", //      MARK_KINDS: per-chart-kind build/draw dispatch registry
  "60_entries.js", //    anywidget + standalone entry points, export tail
];

const here = dirname(fileURLToPath(import.meta.url));
const checkOnly = process.argv.includes("--check");
const src = PARTS.map((p) => readFileSync(join(here, "src", p), "utf8")).join("");
const outDir = join(here, "..", "python", "fastcharts", "static");

// standalone build: strip the export tail, expose a window global.
const marker = "// ---- exports ----";
const cut = src.indexOf(marker);
if (cut < 0) throw new Error("export marker not found in 60_entries.js");
const body = src.slice(0, cut);
const iife = `(() => {\n${body}\nwindow.fastcharts = { render, renderStandalone, ChartView, MARK_KINDS, markOf };\n})();\n`;

const outputs = [
  ["index.js", src],
  ["standalone.js", iife],
];

if (checkOnly) {
  const stale = [];
  for (const [name, expected] of outputs) {
    const path = join(outDir, name);
    let actual = null;
    try {
      actual = readFileSync(path, "utf8");
    } catch {
      stale.push(`${name} missing`);
      continue;
    }
    if (actual !== expected) stale.push(`${name} is stale`);
  }
  if (stale.length) {
    console.error(
      `static JS bundle check failed: ${stale.join(", ")}. Run \`node js/build.mjs\` and commit python/fastcharts/static/*.js.`
    );
    process.exit(1);
  }
  console.log(`static JS bundles are fresh (${PARTS.length} parts)`);
} else {
  mkdirSync(outDir, { recursive: true });
  for (const [name, data] of outputs) writeFileSync(join(outDir, name), data);
  console.log(`built static/index.js and static/standalone.js from ${PARTS.length} parts`);
}
