#!/usr/bin/env node
// Dependency-free "bundler": the client is a single hand-written ES module, so
// building = copying it (anywidget ESM) and wrapping it (standalone IIFE for
// static HTML export). No npm, no registry, no supply chain — deliberate (§33).
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "src", "fastcharts.js"), "utf8");
const outDir = join(here, "..", "python", "fastcharts", "static");
mkdirSync(outDir, { recursive: true });

// anywidget build: the module as-is.
writeFileSync(join(outDir, "index.js"), src);

// standalone build: strip the export tail, expose a window global.
const marker = "// ---- exports ----";
const cut = src.indexOf(marker);
if (cut < 0) throw new Error("export marker not found in fastcharts.js");
const body = src.slice(0, cut);
const iife = `(() => {\n${body}\nwindow.fastcharts = { render, renderStandalone, ChartView };\n})();\n`;
writeFileSync(join(outDir, "standalone.js"), iife);

console.log("built static/index.js and static/standalone.js");
