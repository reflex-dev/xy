// Screenshot sheet.html (written by make_sheet.py) into contact_sheet.png.
// Usage: node examples/legend_overlap/shoot_sheet.js   (from repo root)
const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1420, height: 900 }, deviceScaleFactor: 1.5 });
  await page.goto('file://' + path.join(__dirname, 'sheet.html'));
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(__dirname, 'contact_sheet.png'), fullPage: true });
  await browser.close();
})();
