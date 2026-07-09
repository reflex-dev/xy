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
  "46_worker.js", //     standalone density re-bin worker (blob URL, off-main-thread)
  "50_chartview.js", //  ChartView core: layout, GL, marks, draw, chrome, pick
  "51_annotations.js", // + annotation canvas overlay (prototype augmentation)
  "52_tooltip.js", //    + hover->row tooltip resolution + DOM
  "53_interaction.js", //+ pointer/drag/wheel, selection, modebar, view anim
  "54_kernel.js", //     + kernel comm: view-requests, append, drill (§16)
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
  // GRID_VS is the fullscreen-quad vertex stage shared by density + heatmap:
  // it maps via u_view (data-space window), not per-vertex u_*map attributes.
  const VIEWMAP_EXEMPT = new Set(["GRID_VS"]);
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

// Compact the shipped bundles: strip comments, leading indentation, and blank
// lines — nothing else. Not a renaming minifier; every code token survives
// verbatim (the client-security test greps exact source lines in the built
// bundles). String/template/regex-literal content is untouched: GLSL shaders
// live in template literals and keep their own comments. Line structure is
// preserved (a removed multi-line block comment leaves one newline), so ASI
// behavior cannot change. Payoff: every `Figure.to_html()` inlines the
// standalone bundle, and the anywidget ESM parses on first chart paint — the
// small-data TTFR path (audit small-data #3).
function compact(source) {
  const n = source.length;
  let out = "";
  let i = 0;
  // Frame stack tracks template-literal nesting: `${` pushes a code frame,
  // its matching `}` pops back into the template. `brace` counts plain
  // braces inside a code frame so object literals don't pop early.
  const frames = [{ mode: "code", brace: 0 }];
  let atLineStart = true;
  const emit = (ch) => {
    out += ch;
    atLineStart = ch === "\n";
  };
  while (i < n) {
    const top = frames[frames.length - 1];
    const c = source[i];
    const c2 = source[i + 1];
    if (top.mode === "template") {
      if (c === "\\") {
        emit(c);
        if (i + 1 < n) emit(source[i + 1]);
        i += 2;
        continue;
      }
      if (c === "`") {
        emit(c);
        frames.pop();
        i++;
        continue;
      }
      if (c === "$" && c2 === "{") {
        emit(c);
        emit(c2);
        frames.push({ mode: "code", brace: 0 });
        i += 2;
        continue;
      }
      emit(c);
      i++;
      continue;
    }
    // mode === "code"
    if (atLineStart && (c === " " || c === "\t")) {
      i++; // strip indentation
      continue;
    }
    if (c === "\n") {
      if (!atLineStart) emit("\n"); // collapse blank lines
      i++;
      continue;
    }
    if (c === "/" && c2 === "/") {
      while (i < n && source[i] !== "\n") i++;
      continue; // the newline itself is handled above
    }
    if (c === "/" && c2 === "*") {
      const end = source.indexOf("*/", i + 2);
      const closed = end >= 0 ? end + 2 : n;
      const removed = source.slice(i, closed);
      // Keep separation so `a/* */b` can't fuse tokens; keep a newline if the
      // comment spanned lines so the following line still starts a line.
      emit(removed.includes("\n") ? "\n" : " ");
      i = closed;
      continue;
    }
    if (c === "'" || c === '"') {
      emit(c);
      i++;
      while (i < n) {
        const s = source[i];
        emit(s);
        i++;
        if (s === "\\") {
          if (i < n) {
            emit(source[i]);
            i++;
          }
          continue;
        }
        if (s === c) break;
      }
      continue;
    }
    if (c === "`") {
      emit(c);
      frames.push({ mode: "template" });
      i++;
      continue;
    }
    if (c === "{") {
      top.brace++;
      emit(c);
      i++;
      continue;
    }
    if (c === "}") {
      if (top.brace > 0) {
        top.brace--;
        emit(c);
      } else if (frames.length > 1) {
        frames.pop(); // close of a ${...} interpolation
        emit(c);
      } else {
        emit(c);
      }
      i++;
      continue;
    }
    emit(c);
    i++;
  }
  return out;
}

// standalone build: strip the export tail, expose a window global.
const marker = "// ---- exports ----";
const cut = src.indexOf(marker);
if (cut < 0) throw new Error("export marker not found in 60_entries.js");
// The marker must own its whole line: exportTail is emitted raw into index.js,
// so any text trailing the marker on its line would land as bare (invalid) code
// in the ESM bundle. Split at the line boundary and reject a non-empty tail.
const markerLineEnd = src.indexOf("\n", cut);
const trailing = src.slice(cut + marker.length, markerLineEnd < 0 ? undefined : markerLineEnd);
if (trailing.trim()) {
  throw new Error(`text after "${marker}" would leak into index.js: "${trailing.trim()}"`);
}
const body = compact(src.slice(0, cut));
// Parse-validate the compacted body: a compactor bug must fail the build, not
// ship a corrupted client. new Function parses (without executing) everything
// but import/export syntax — the body is export-free by construction.
new Function(body);
const exportTail = markerLineEnd < 0 ? "" : src.slice(markerLineEnd + 1);
const iife = `(() => {\n${body}\nwindow.fastcharts = { render, renderStandalone, ChartView, MARK_KINDS, markOf };\n})();\n`;
new Function(iife);

const outputs = [
  ["index.js", body + "\n" + exportTail.trimStart()],
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
