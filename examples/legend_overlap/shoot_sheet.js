// Screenshot sheet.html (written by make_sheet.py) into contact_sheet.png.
// Usage: node examples/legend_overlap/shoot_sheet.js   (from repo root)
// Playwright finds its own browser; set XY_CHROMIUM to use another binary.
const { chromium } = require('playwright');
const path = require('path');
const { pathToFileURL } = require('url');

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.XY_CHROMIUM || undefined });
  const page = await browser.newPage({ viewport: { width: 1420, height: 900 }, deviceScaleFactor: 1.5 });
  await page.goto(pathToFileURL(path.join(__dirname, 'sheet.html')).href);
  // Every chart image decoded, so the sheet is not captured half-loaded.
  await page.waitForFunction(() => [...document.images].every((img) => img.complete));
  await page.screenshot({ path: path.join(__dirname, 'contact_sheet.png'), fullPage: true });
  await browser.close();
})();
