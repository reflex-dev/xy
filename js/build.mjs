#!/usr/bin/env node
// Build the render client. The source is TypeScript ES modules under src/
// (one module per former concat part; import order replaces concat order).
// Vite (rolldown + oxc) bundles and minifies them into the two committed
// artifacts in python/xy/static/ — the minified bundles are what ships to the
// client (§33 amended: vite/typescript are the only, dev-time-only, npm deps):
//   index.js      — ESM bundle (anywidget `_esm`; named exports + default)
//   standalone.js — IIFE bundle exposing `window.xy`, inlined by
//                   `Figure.to_html()` into static HTML exports
// Steps: tsc typecheck → shader-convention lint → vite build (×2 formats).
// `--check` rebuilds into a scratch dir and byte-compares against the
// committed artifacts (the CI freshness gate); it never touches static/.
import { mkdtempSync, readFileSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const checkOnly = process.argv.includes("--check");
const staticDir = join(root, "python", "xy", "static");

// Typecheck first: a bundle must never be built from source tsc rejects
// (esbuild strips types without checking them, so this is the only gate).
{
  // Invoke tsc through the current node binary rather than the .bin shim:
  // on Windows the shim is tsc.cmd, which spawnSync cannot exec (ENOENT).
  const tsc = join(root, "node_modules", "typescript", "bin", "tsc");
  const res = spawnSync(process.execPath, [tsc, "-p", join(here, "tsconfig.json")], {
    stdio: "inherit",
  });
  if (res.error) {
    console.error(`tsc failed to start (${res.error.message}); run \`npm install\` first`);
    process.exit(1);
  }
  if (res.status !== 0) process.exit(res.status ?? 1);
}

// Shader convention lint (renderer audit R5). The conventions are load-bearing:
// a non-highp fragment default already caused one precision-mismatch hunt
// (§16), and the u_*map uniform pair is how every mark stays pan/zoom-cheap.
// Enforce at build time so a new mark kind can't drift silently.
{
  // Fullscreen/texture quads position via corner constants, not data maps.
  // GRID_VS is the fullscreen-quad vertex stage shared by density + heatmap:
  // it maps via u_view (data-space window), not per-vertex u_*map attributes.
  const VIEWMAP_EXEMPT = new Set(["GRID_VS"]);
  const glSrc = readFileSync(join(here, "src", "40_gl.ts"), "utf8");
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

const { build } = await import("vite");

/** Build both bundles into outDir. The ESM build keeps 60_entries' export
 * shape, including its frozen semantic-test seam. The IIFE build enters through
 * 61_standalone so only the public namespace is assigned to top-level `var xy`
 * (`window.xy` in the classic inline <script> emitted by Figure.to_html()). */
async function buildBundles(outDir) {
  const formats = [
    { format: "es", fileName: "index.js", entry: "60_entries.ts" },
    { format: "iife", fileName: "standalone.js", entry: "61_standalone.ts" },
  ];
  for (const { format, fileName, entry } of formats) {
    await build({
      configFile: false,
      root: here,
      logLevel: "warn",
      clearScreen: false,
      build: {
        outDir,
        emptyOutDir: false,
        copyPublicDir: false,
        target: "es2022",
        minify: true, // oxc, vite 8's built-in minifier
        // The committed artifacts are byte-compared by --check; keep the
        // build free of environment-dependent output (no gzip size probe).
        reportCompressedSize: false,
        // Not `build.lib`: lib mode keeps whitespace in ES output by design;
        // these artifacts ship inside notebooks/HTML, so both formats minify
        // fully. The entry's export shape is preserved verbatim.
        rollupOptions: {
          input: join(here, "src", entry),
          preserveEntrySignatures: "strict",
          output: {
            format,
            entryFileNames: fileName,
            name: "xy",
            exports: "named",
          },
        },
      },
    });
  }
}

if (checkOnly) {
  const scratch = mkdtempSync(join(tmpdir(), "xy-js-check-"));
  try {
    await buildBundles(scratch);
    const stale = [];
    for (const name of ["index.js", "standalone.js"]) {
      let actual = null;
      try {
        actual = readFileSync(join(staticDir, name), "utf8");
      } catch {
        stale.push(`${name} missing`);
        continue;
      }
      const expected = readFileSync(join(scratch, name), "utf8");
      if (actual !== expected) stale.push(`${name} is stale`);
    }
    if (stale.length) {
      console.error(
        `static JS bundle check failed: ${stale.join(", ")}. Run \`node js/build.mjs\` and commit python/xy/static/*.js.`
      );
      process.exit(1);
    }
    console.log("static JS bundles are fresh");
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
} else {
  mkdirSync(staticDir, { recursive: true });
  await buildBundles(staticDir);
  console.log("built minified static/index.js and static/standalone.js with vite");
}
