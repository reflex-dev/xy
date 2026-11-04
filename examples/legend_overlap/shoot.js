// Screenshot each case in headless Chromium and report legend-vs-plot overlap.
// Usage: node examples/legend_overlap/shoot.js   (from repo root)
// Playwright finds its own browser; set XY_CHROMIUM to use another binary.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

(async () => {
  const dir = path.join(__dirname, 'html');
  const out = path.join(__dirname, 'png');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({
    executablePath: process.env.XY_CHROMIUM || undefined,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const page = await browser.newPage({ viewport: { width: 960, height: 420 }, deviceScaleFactor: 2 });
  const report = [];
  for (const f of fs.readdirSync(dir).filter((n) => n.endsWith('.html')).sort()) {
    const errors = [];
    page.removeAllListeners('pageerror');
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto(pathToFileURL(path.join(dir, f)).href);
    try {
      // Ready when the legend exists and two frames have painted after it.
      await page.waitForSelector('[data-xy-legend-loc]', { state: 'attached', timeout: 10000 });
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    } catch (err) {
      errors.push(`legend never rendered: ${err}`);
    }
    const info = await page.evaluate(() => {
      const lg = document.querySelector('[data-xy-legend-loc]');
      if (!lg) return null;
      const r = lg.getBoundingClientRect();
      return { loc: lg.dataset.xyLegendLoc, auto: lg.dataset.xyLegendAutoLoc || null,
               columns: lg.dataset.xyLegendColumns ? Number(lg.dataset.xyLegendColumns) : null,
               w: Math.round(r.width), h: Math.round(r.height),
               scroll: lg.scrollHeight > lg.clientHeight + 1 };
    });
    // Crop to the chart root (the element that owns the legend), or the whole
    // page when the legend failed to render, so the failure is still recorded.
    const box = await page.evaluate(() => {
      const lg = document.querySelector('[data-xy-legend-loc]');
      const el = (lg && lg.closest('.xy')) || document.body;
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, width: Math.max(1, r.width), height: Math.max(1, r.height) };
    });
    await page.screenshot({ path: path.join(out, f.replace('.html', '.png')), clip: box });
    report.push({ file: f, legend: info, errors });
  }
  fs.writeFileSync(path.join(__dirname, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 1));
  await browser.close();
})();
