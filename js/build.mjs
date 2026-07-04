#!/usr/bin/env node
// Dependency-free "bundler": the client is hand-written ES-module source split
// into ordered parts under src/ (plain script content; exports live only in the
// final part). Building = concatenating them (anywidget ESM) and wrapping the
// export-free body (standalone IIFE for static HTML export). No npm, no
// registry, no supply chain — deliberate (§33).
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
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
const src = PARTS.map((p) => readFileSync(join(here, "src", p), "utf8")).join("");
const outDir = join(here, "..", "python", "fastcharts", "static");
mkdirSync(outDir, { recursive: true });

// anywidget build: the concatenated module as-is.
writeFileSync(join(outDir, "index.js"), src);

// standalone build: strip the export tail, expose a window global.
const marker = "// ---- exports ----";
const cut = src.indexOf(marker);
if (cut < 0) throw new Error("export marker not found in 60_entries.js");
const body = src.slice(0, cut);
const iife = `(() => {\n${body}\nwindow.fastcharts = { render, renderStandalone, ChartView, MARK_KINDS, markOf };\n})();\n`;
writeFileSync(join(outDir, "standalone.js"), iife);

console.log(`built static/index.js and static/standalone.js from ${PARTS.length} parts`);
