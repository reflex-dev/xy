// Screenshot each case in headless Chromium and report legend-vs-plot overlap.
// Usage: node examples/legend_overlap/shoot.js   (from repo root)
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const dir = path.join(__dirname, 'html');
  const out = path.join(__dirname, 'png');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 560, height: 340 }, deviceScaleFactor: 2 });
  const report = [];
  for (const f of fs.readdirSync(dir).filter((n) => n.endsWith('.html')).sort()) {
    const errors = [];
    page.removeAllListeners('pageerror');
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto('file://' + path.join(dir, f));
    await page.waitForTimeout(1500);
    const info = await page.evaluate(() => {
      const lg = document.querySelector('[data-xy-legend-loc]');
      if (!lg) return null;
      const r = lg.getBoundingClientRect();
      return { loc: lg.dataset.xyLegendLoc, auto: lg.dataset.xyLegendAutoLoc || null,
               w: Math.round(r.width), h: Math.round(r.height),
               scroll: lg.scrollHeight > lg.clientHeight + 1 };
    });
    // Crop to the chart root (the element that owns the legend).
    const box = await page.evaluate(() => {
      const lg = document.querySelector('[data-xy-legend-loc]');
      let el = lg;
      while (el && el.parentElement && el.parentElement !== document.body) el = el.parentElement;
      const r = (el || document.body).getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height };
    });
    await page.screenshot({ path: path.join(out, f.replace('.html', '.png')), clip: box });
    report.push({ file: f, legend: info, errors });
  }
  fs.writeFileSync(path.join(__dirname, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 1));
  await browser.close();
})();
