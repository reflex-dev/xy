// Render the six legend-overlap cases with TanStack Charts' default legend.
import fs from 'node:fs';
import { areaY, barY, colorLegend, createChartScene, defineChart, group, lineY, renderChartSvg, stack } from '@tanstack/charts';
import { scaleLinear } from '@tanstack/charts/scales/linear';
import { scaleBand } from '@tanstack/charts/scales/band';

const data = JSON.parse(fs.readFileSync(new URL('./data.json', import.meta.url)));
const long = (obj) => Object.entries(obj).flatMap(([series, ys]) => ys.map((y, i) => ({ x: i, y, series })));
const months = (key) => ({ x: { scale: scaleLinear }, y: { scale: scaleLinear, grid: true } });
const legend = { legend: colorLegend() };

const lines = (key) => defineChart({
  marks: [lineY(long(data[key]), { x: 'x', y: 'y', color: 'series' })],
  scales: months(key), color: legend,
});
const defs = {
  '1_rising_lines': lines('1_rising_lines'),
  '2_many_series': lines('2_many_series'),
  '3_long_names': lines('3_long_names'),
  '4_stacked_area': defineChart({
    marks: [areaY(long(data['4_stacked_area']), { x: 'x', y: 'y', color: 'series', layout: stack(), fillOpacity: 0.6 })],
    scales: months(), color: legend,
  }),
  '5_grouped_columns': defineChart({
    marks: [barY(Object.entries(data['5_grouped_columns']).flatMap(([series, ys]) =>
      ys.map((y, i) => ({ x: ['Q1', 'Q2', 'Q3', 'Q4'][i], y, series }))),
      { x: 'x', y: 'y', color: 'series', layout: group() })],
    scales: { x: { scale: () => scaleBand().padding(0.2) }, y: { scale: scaleLinear, grid: true } }, color: legend,
  }),
  '6_small_card': lines('6_small_card'),
};
fs.mkdirSync(new URL('./svg/', import.meta.url), { recursive: true });
for (const [key, def] of Object.entries(defs)) {
  const size = key === '6_small_card' ? { width: 320, height: 200 } : { width: 520, height: 300 };
  const scene = createChartScene(def, size);
  // renderChartSvg emits an inline-embeddable <svg> (no xmlns, 100% size);
  // make it a standalone file with a white background and a fixed pixel size.
  const inline = renderChartSvg(scene, { idPrefix: key, ariaLabel: key });
  const head = '<svg class="ts-chart" width="100%" height="100%"';
  // Fail loudly if a TanStack release changes this markup: a silent no-op
  // would write SVGs that do not render as standalone images.
  if (!inline.startsWith(head) || !/^<svg[^>]*style="/.test(inline)) {
    throw new Error(`unexpected renderChartSvg markup for ${key}: ${inline.slice(0, 120)}`);
  }
  const svg = inline
    .replace(head, `<svg xmlns="http://www.w3.org/2000/svg" class="ts-chart" width="${size.width}" height="${size.height}"`)
    .replace(/(<svg[^>]*style=")/, '$1background:#fff;color:#111;font-family:system-ui,sans-serif;');
  fs.writeFileSync(new URL(`./svg/${key}.svg`, import.meta.url), svg);
  console.log('wrote', key, size.width + 'x' + size.height);
}
