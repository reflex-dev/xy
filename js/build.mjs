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
// Normalize CRLF: a Windows checkout with autocrlf otherwise mixes CRLF part
// content with the wrapper's literal \n, making the freshness check fail on
// exactly one platform. Build output is LF everywhere, deterministically.
const readText = (p) => readFileSync(p, "utf8").replace(/\r\n/g, "\n");
const src = PARTS.map((p) => readText(join(here, "src", p))).join("");
const outDir = join(here, "..", "python", "fastcharts", "static");

// Shader convention lint (renderer audit R5). The conventions are load-bearing:
// a non-highp fragment default already caused one precision-mismatch hunt
// (§16), and the u_*map uniform pair is how every mark stays pan/zoom-cheap.
// Enforce at build time so a new mark kind can't drift silently.
{
  // Fullscreen/texture quads position via corner constants, not data maps.
  const VIEWMAP_EXEMPT = new Set(["DENSITY_VS", "HEATMAP_VS"]);
  const glSrc = readText(join(here, "src", "40_gl.js"));
  const errs = [];
  let shaders = 0;
  for (const m of glSrc.matchAll(/const (\w+_(?:VS|FS)) = `([^`]*)`/g)) {
    const [, name, shader] = m;
    shaders++;
    if (!shader.startsWith("#version 300 es")) {
      errs.push(`${name}: must start with '#version 300 es'`);
    }
    if (name.endsWith("_FS") && !shader.includes("precision highp float;")) {
      errs.push(`${name}: fragment shaders must declare 'precision highp float;' (§16)`);
    }
    if (name.endsWith("_VS") && !VIEWMAP_EXEMPT.has(name) && !/u_\w*map/.test(shader)) {
      errs.push(
        `${name}: vertex shaders map data via u_*map uniforms (or add to VIEWMAP_EXEMPT with a reason)`
      );
    }
    for (const u of shader.matchAll(/uniform\s+\w+\s+(\w+)/g)) {
      if (!u[1].startsWith("u_")) errs.push(`${name}: uniform '${u[1]}' must be u_-prefixed`);
    }
    if (name.endsWith("_VS")) {
      for (const a of shader.matchAll(/^\s*in\s+\w+\s+(\w+)/gm)) {
        if (!a[1].startsWith("a")) errs.push(`${name}: attribute '${a[1]}' must be a-prefixed`);
      }
    }
  }
  if (shaders === 0) errs.push("shader lint found no shaders — extraction regex is broken");
  if (errs.length) {
    console.error("shader convention lint failed:\n  " + errs.join("\n  "));
    process.exit(1);
  }
}

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
      actual = readText(path);
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
