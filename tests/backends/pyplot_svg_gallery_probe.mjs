import fs from "node:fs";
import { pathToFileURL } from "node:url";

import { chromium } from "playwright";

const manifestPath = process.argv[2];
const executablePath = process.argv[3];
if (!manifestPath || !executablePath) {
  throw new Error("usage: node pyplot_svg_gallery_probe.mjs MANIFEST CHROMIUM");
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: [
    "--allow-file-access-from-files",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
  ],
});

function requireEqual(actual, expected, message) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${message}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

async function openSvg(file) {
  const page = await browser.newPage({ viewport: { width: 900, height: 700 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await page.goto(pathToFileURL(file).href, { waitUntil: "load", timeout: 30_000 });
  return { page, pageErrors };
}

async function verifyHistogram(file) {
  const { page, pageErrors } = await openSvg(file);
  const legend = page.locator("#leg_patch_0");
  const histogram = page.locator('[id^="hist_0_patch_"]');
  if ((await legend.count()) !== 1 || (await histogram.count()) === 0) {
    throw new Error("histogram SVG is missing legend or bar ids");
  }

  await legend.click({ force: true });
  await page.waitForFunction(() =>
    [...document.querySelectorAll('[id^="hist_0_patch_"]')].every(
      (element) => element.style.opacity === "0",
    ),
  );
  requireEqual(
    await histogram.evaluateAll((elements) => elements.map((element) => element.style.opacity)),
    Array(await histogram.count()).fill("0"),
    "legend click must hide the first histogram",
  );
  requireEqual(
    await page.locator("#leg_text_0").evaluate((element) => element.style.opacity),
    "0.5",
    "legend click must dim its text",
  );

  await legend.click({ force: true });
  await page.waitForFunction(() =>
    [...document.querySelectorAll('[id^="hist_0_patch_"]')].every(
      (element) => element.style.opacity === "1",
    ),
  );
  requireEqual(pageErrors, [], "histogram browser script raised an error");
  await page.close();
}

async function verifyTooltip(file) {
  const { page, pageErrors } = await openSvg(file);
  // The upstream source adds the same Rectangle twice. XMLID consequently
  // attaches the callbacks to the last duplicate, which is the authoritative
  // interactive element in the emitted SVG.
  const patch = page.locator('#mypatch_000[onmouseover="ShowTooltip(this)"]');
  const tooltip = page.locator("#mytooltip_000");
  requireEqual(await tooltip.getAttribute("visibility"), "hidden", "tooltip initial state");

  await patch.hover({ force: true });
  await page.waitForFunction(
    () => document.getElementById("mytooltip_000")?.getAttribute("visibility") === "visible",
  );
  requireEqual(await tooltip.getAttribute("visibility"), "visible", "tooltip hover state");

  await page.locator("svg").hover({ position: { x: 2, y: 2 }, force: true });
  await page.waitForFunction(
    () => document.getElementById("mytooltip_000")?.getAttribute("visibility") === "hidden",
  );
  requireEqual(pageErrors, [], "tooltip browser script raised an error");
  await page.close();
}

async function svgLinks(file) {
  const { page, pageErrors } = await openSvg(file);
  const links = await page.locator("a").evaluateAll((anchors) =>
    anchors
      .map(
        (anchor) =>
          anchor.getAttribute("href") ||
          anchor.getAttributeNS("http://www.w3.org/1999/xlink", "href") ||
          anchor.href?.baseVal ||
          "",
      )
      .filter(Boolean)
      .sort(),
  );
  requireEqual(pageErrors, [], "hyperlink SVG raised a browser error");
  await page.close();
  return links;
}

const results = [];
try {
  for (const artifact of manifest.artifacts) {
    await verifyHistogram(artifact.histogram);
    await verifyTooltip(artifact.tooltip);
    requireEqual(
      await svgLinks(artifact.scatter),
      ["https://www.bbc.com/news", "https://www.google.com/"],
      `${artifact.engine} scatter hyperlinks`,
    );
    requireEqual(
      await svgLinks(artifact.image),
      ["https://www.google.com/"],
      `${artifact.engine} image hyperlink`,
    );
    results.push({ engine: artifact.engine, passed: true });
  }
} finally {
  await browser.close();
}

process.stdout.write(`${JSON.stringify({ results })}\n`);
