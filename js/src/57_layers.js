// ---------------------------------------------------------------------------
// Finance layer registry — canvas overlays above WebGL marks.
//
// This mirrors MARK_KINDS for non-data layers. Marks own binary columns and
// WebGL draw calls; layers own small JSON anchors/props plus canvas geometry.
// ---------------------------------------------------------------------------

function rgba(c, alpha = 1) {
  return `rgba(${Math.round(c[0] * 255)},${Math.round(c[1] * 255)},${Math.round(c[2] * 255)},${alpha})`;
}

function layerAnchor(view, layer, name) {
  return view._anchorPoint(layer.anchors && layer.anchors[name]);
}

function finitePoint(p) {
  return p && Number.isFinite(p.x) && Number.isFinite(p.y);
}

function xFrom(view, p, fallback) {
  return p && p.hasX && Number.isFinite(p.x) ? view._dataToScreenX(p.x) : fallback;
}

function yFrom(view, p, fallback) {
  return p && p.hasY && Number.isFinite(p.y) ? view._dataToScreenY(p.y) : fallback;
}

function drawLabel(ctx, text, x, y, color, bg) {
  if (!text) return;
  ctx.save();
  ctx.font = "11px system-ui,sans-serif";
  const w = ctx.measureText(text).width + 10;
  const h = 18;
  ctx.fillStyle = bg || "rgba(15,19,28,.82)";
  ctx.strokeStyle = "rgba(255,255,255,.15)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  roundedRect(ctx, x, y - h / 2, w, h, 4);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = color || "#fff";
  ctx.fillText(text, x + 5, y + 4);
  ctx.restore();
}

function roundedRect(ctx, x, y, w, h, r) {
  const rr = Math.min(r, Math.abs(w) / 2, Math.abs(h) / 2);
  ctx.moveTo(x + rr, y);
  ctx.lineTo(x + w - rr, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
  ctx.lineTo(x + w, y + h - rr);
  ctx.quadraticCurveTo(x + w, y + h, x + w - rr, y + h);
  ctx.lineTo(x + rr, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - rr);
  ctx.lineTo(x, y + rr);
  ctx.quadraticCurveTo(x, y, x + rr, y);
}

function drawLine(ctx, x1, y1, x2, y2, color, width = 1.5, dash = []) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.setLineDash(dash);
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
  ctx.restore();
}

function drawHandle(ctx, x, y, color) {
  ctx.save();
  ctx.fillStyle = color;
  ctx.strokeStyle = "rgba(255,255,255,.9)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(x, y, 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

function drawPosition(view, ctx, layer) {
  const a = layer.anchors || {};
  const entry = view._anchorPoint(a.entry);
  const stop = view._anchorPoint(a.stop);
  const target = view._anchorPoint(a.target);
  const end = view._anchorPoint(a.end);
  if (!entry || !Number.isFinite(entry.y) || !stop || !target) return;
  const p = view.plot;
  const x1 = xFrom(view, entry, p.x);
  const x2 = xFrom(view, end, p.x + p.w);
  const yEntry = view._dataToScreenY(entry.y);
  const yStop = yFrom(view, stop, yEntry);
  const yTarget = yFrom(view, target, yEntry);
  const targetColor = view._layerColor(layer, "target_color", [0.06, 0.67, 0.47, 1]);
  const stopColor = view._layerColor(layer, "stop_color", [0.9, 0.24, 0.29, 1]);
  const lineColor = view._layerColor(layer, "line_color", [0.78, 0.82, 0.9, 1]);
  const targetCss = rgba(targetColor, 0.20);
  const stopCss = rgba(stopColor, 0.20);
  ctx.save();
  ctx.fillStyle = targetCss;
  ctx.fillRect(x1, Math.min(yEntry, yTarget), x2 - x1, Math.abs(yTarget - yEntry));
  ctx.fillStyle = stopCss;
  ctx.fillRect(x1, Math.min(yEntry, yStop), x2 - x1, Math.abs(yStop - yEntry));
  ctx.strokeStyle = rgba(lineColor, 0.95);
  ctx.lineWidth = 1.25;
  for (const y of [yTarget, yEntry, yStop]) {
    ctx.beginPath();
    ctx.moveTo(x1, y);
    ctx.lineTo(x2, y);
    ctx.stroke();
  }
  ctx.restore();
  const m = layer.metrics || {};
  const side = layer.side === "short" ? "SHORT" : layer.side === "long" ? "LONG" : "";
  drawLabel(ctx, `${side ? side + " " : ""}R:R ${Number(m.risk_reward || 0).toFixed(2)}`, x2 + 6, yEntry, "#fff");
  drawLabel(ctx, `TP ${fmtLinear(target.y, 1)}`, x1 + 6, yTarget, "#fff", rgba(targetColor, 0.9));
  drawLabel(ctx, `SL ${fmtLinear(stop.y, 1)}`, x1 + 6, yStop, "#fff", rgba(stopColor, 0.9));
  drawHandle(ctx, x1, yEntry, rgba(lineColor, 1));
}

function drawProjection(view, ctx, layer) {
  const start = layerAnchor(view, layer, "start") || layerAnchor(view, layer, "origin");
  const target = layerAnchor(view, layer, "target");
  if (!finitePoint(start) || !finitePoint(target)) return;
  const x1 = view._dataToScreenX(start.x);
  const y1 = view._dataToScreenY(start.y);
  const x2 = view._dataToScreenX(target.x);
  const y2 = view._dataToScreenY(target.y);
  const color = rgba(view._layerColor(layer, "color", [0.23, 0.51, 0.96, 1]), 1);
  drawLine(ctx, x1, y1, x2, y2, color, 2, [5, 4]);
  drawHandle(ctx, x1, y1, color);
  drawHandle(ctx, x2, y2, color);
  drawLabel(ctx, layer.kind === "sector" ? "Sector" : "Forecast", x2 + 6, y2, "#fff");
}

function drawSector(view, ctx, layer) {
  const origin = layerAnchor(view, layer, "origin");
  const horizon = layerAnchor(view, layer, "horizon");
  const target = layerAnchor(view, layer, "target");
  if (!origin || !target || !Number.isFinite(origin.x) || !Number.isFinite(origin.y)) return;
  const p = view.plot;
  const x0 = view._dataToScreenX(origin.x);
  const y0 = view._dataToScreenY(origin.y);
  const x1 = xFrom(view, horizon, xFrom(view, target, p.x + p.w));
  const y1 = view._dataToScreenY(target.y);
  const color = view._layerColor(layer, "color", [0.23, 0.51, 0.96, 1]);
  ctx.save();
  ctx.fillStyle = rgba(color, 0.14);
  ctx.strokeStyle = rgba(color, 0.9);
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x1, y1);
  ctx.lineTo(x1, y0 + (y0 - y1));
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.restore();
  drawHandle(ctx, x0, y0, rgba(color, 1));
  drawLabel(ctx, "Sector", x1 + 6, y1, "#fff");
}

function drawVolumeProfile(view, ctx, layer, opts = {}) {
  const props = layer.props || {};
  const profile = props.profile;
  if (!profile || !Array.isArray(profile.total) || !profile.total.length) return false;
  const p = view.plot;
  const total = profile.total;
  const up = Array.isArray(profile.up) ? profile.up : total;
  const down = Array.isArray(profile.down) ? profile.down : [];
  const low = profile.price_low || [];
  const high = profile.price_high || [];
  const valueArea = profile.value_area || [];
  const maxTotal = Number(profile.max_total || Math.max(...total, 0));
  if (!maxTotal) return false;

  const color = view._layerColor(layer, "color", [0.56, 0.64, 0.76, 1]);
  const upColor = view._layerColor(layer, "up_color", [0.13, 0.67, 0.58, 1]);
  const downColor = view._layerColor(layer, "down_color", [0.95, 0.21, 0.27, 1]);
  const pocColor = view._layerColor(layer, "poc_color", [0.96, 0.68, 0.19, 1]);
  const mode = props.volume || "total";
  const rangeW = Math.abs((opts.x1 || p.x + p.w) - (opts.x0 || p.x));
  const maxW = Math.min(
    230,
    Math.max(60, (opts.anchored ? p.w : rangeW || p.w) * 0.34),
    Math.max(40, p.w - 20)
  );
  let right = opts.anchored ? p.x + p.w - 7 : Math.max(opts.x0 || p.x, opts.x1 || p.x + p.w) - 4;
  right = Math.max(p.x + maxW + 8, Math.min(p.x + p.w - 6, right));
  const left = Math.max(p.x + 8, right - maxW);
  const availableW = right - left;

  ctx.save();
  for (let i = 0; i < total.length; i++) {
    const t = Number(total[i] || 0);
    if (t <= 0 || !Number.isFinite(Number(low[i])) || !Number.isFinite(Number(high[i]))) continue;
    const y0 = view._dataToScreenY(Number(high[i]));
    const y1 = view._dataToScreenY(Number(low[i]));
    const top = Math.max(p.y, Math.min(y0, y1));
    const bottom = Math.min(p.y + p.h, Math.max(y0, y1));
    const h = Math.max(1, bottom - top - 0.5);
    const w = Math.max(1, (t / maxTotal) * availableW);
    const x = right - w;
    const isVa = Boolean(valueArea[i]);
    const isPoc = i === Number(profile.poc_index);

    if (mode === "up_down") {
      const upShare = t ? Math.max(0, Number(up[i] || 0)) / t : 0;
      const upW = Math.max(0, Math.min(w, w * upShare));
      const downW = w - upW;
      ctx.fillStyle = rgba(downColor, isVa ? 0.38 : 0.22);
      ctx.fillRect(x, top, downW, h);
      ctx.fillStyle = rgba(upColor, isVa ? 0.44 : 0.26);
      ctx.fillRect(x + downW, top, upW, h);
    } else if (mode === "delta") {
      const delta = Number((profile.delta || [])[i] || 0);
      const center = left + availableW / 2;
      const dw = Math.max(1, Math.abs(delta) / maxTotal * (availableW / 2));
      ctx.fillStyle = delta >= 0 ? rgba(upColor, isVa ? 0.48 : 0.30) : rgba(downColor, isVa ? 0.46 : 0.28);
      ctx.fillRect(delta >= 0 ? center : center - dw, top, dw, h);
    } else {
      ctx.fillStyle = rgba(color, isVa ? 0.42 : 0.22);
      ctx.fillRect(x, top, w, h);
    }

    if (isPoc) {
      ctx.strokeStyle = rgba(pocColor, 0.95);
      ctx.lineWidth = 1.25;
      ctx.beginPath();
      ctx.moveTo(x, top + h / 2);
      ctx.lineTo(right, top + h / 2);
      ctx.stroke();
    }
  }
  ctx.strokeStyle = rgba(color, 0.55);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(right + 0.5, p.y);
  ctx.lineTo(right + 0.5, p.y + p.h);
  ctx.stroke();
  ctx.restore();
  return true;
}

function volumeSlotWidth(view, xs, i, visibleCount) {
  const x = Number(xs[i]);
  const prev = i > 0 ? Number(xs[i - 1]) : NaN;
  const next = i < xs.length - 1 ? Number(xs[i + 1]) : NaN;
  let left = Number.isFinite(prev)
    ? Math.abs(view._dataToScreenX(x) - view._dataToScreenX(prev))
    : NaN;
  let right = Number.isFinite(next)
    ? Math.abs(view._dataToScreenX(next) - view._dataToScreenX(x))
    : NaN;
  const slot = Math.min(
    Number.isFinite(left) && left > 0 ? left : Infinity,
    Number.isFinite(right) && right > 0 ? right : Infinity
  );
  if (Number.isFinite(slot)) return Math.max(1, Math.min(16, slot * 0.72));
  const pane = view.volumePane || view.plot;
  return Math.max(1, Math.min(12, (pane.w / Math.max(visibleCount, 1)) * 0.72));
}

function drawVolumeBars(view, ctx, layer) {
  const pane = view.volumePane;
  const props = layer.props || {};
  const bars = props.bars;
  if (!pane || !bars || !Array.isArray(bars.x) || !Array.isArray(bars.volume)) return;
  const xs = bars.x;
  const volume = bars.volume;
  const direction = Array.isArray(bars.direction) ? bars.direction : [];
  if (!xs.length || !volume.length) return;
  const { x0, x1 } = view.view;
  const visible = [];
  let maxVol = 0;
  for (let i = 0; i < Math.min(xs.length, volume.length); i++) {
    const x = Number(xs[i]);
    const vol = Number(volume[i]);
    if (!Number.isFinite(x) || !Number.isFinite(vol) || vol < 0) continue;
    if (x < x0 || x > x1) continue;
    visible.push(i);
    if (vol > maxVol) maxVol = vol;
  }
  if (!visible.length || maxVol <= 0) return;

  const upColor = view._layerColor(layer, "up_color", [0.13, 0.67, 0.58, 1]);
  const downColor = view._layerColor(layer, "down_color", [0.95, 0.21, 0.27, 1]);
  const gridColor = view._layerColor(layer, "grid_color", [0.56, 0.64, 0.76, 1]);
  const labelColor = rgba(view._layerColor(layer, "label_color", [0.78, 0.82, 0.9, 1]), 0.78);
  const pad = 3;
  const maxH = Math.max(1, pane.h - pad * 2);

  ctx.save();
  ctx.fillStyle = "rgba(128,128,128,.035)";
  ctx.fillRect(pane.x, pane.y, pane.w, pane.h);
  ctx.strokeStyle = rgba(gridColor, 0.22);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pane.x, Math.round(pane.y) + 0.5);
  ctx.lineTo(pane.x + pane.w, Math.round(pane.y) + 0.5);
  ctx.moveTo(pane.x, Math.round(pane.y + pane.h / 2) + 0.5);
  ctx.lineTo(pane.x + pane.w, Math.round(pane.y + pane.h / 2) + 0.5);
  ctx.stroke();

  for (const i of visible) {
    const x = Number(xs[i]);
    const vol = Number(volume[i]);
    const cx = view._dataToScreenX(x);
    if (cx < pane.x - 20 || cx > pane.x + pane.w + 20) continue;
    const w = volumeSlotWidth(view, xs, i, visible.length);
    const h = Math.max(1, (vol / maxVol) * maxH);
    const y = pane.y + pane.h - h - pad;
    const col = direction[i] ? upColor : downColor;
    ctx.fillStyle = rgba(col, 0.54);
    ctx.fillRect(cx - w / 2, y, w, h);
  }

  ctx.fillStyle = labelColor;
  ctx.font = "11px system-ui,sans-serif";
  ctx.fillText("Volume", pane.x + 4, pane.y + 13);
  ctx.textAlign = "right";
  ctx.fillText(fmtLinear(maxVol, Math.max(maxVol / 2, 1)), pane.x + pane.w - 4, pane.y + 13);
  ctx.restore();
}

function drawAnchoredStudy(view, ctx, layer) {
  const anchor = layerAnchor(view, layer, "anchor") || layerAnchor(view, layer, "start");
  if (!anchor || !Number.isFinite(anchor.x)) return;
  const p = view.plot;
  const x = view._dataToScreenX(anchor.x);
  const color = rgba(view._layerColor(layer, "color", [0.96, 0.68, 0.19, 1]), 1);
  drawLine(ctx, x, p.y, x, p.y + p.h, color, 1.25, [4, 4]);
  const label = layer.kind === "anchored_vwap"
    ? "AVWAP"
    : layer.kind === "anchored_volume_profile"
      ? "AVP"
      : "Volume profile";
  drawLabel(ctx, label, x + 6, p.y + 16, "#fff");
  if (layer.kind === "anchored_volume_profile") {
    drawVolumeProfile(view, ctx, layer, { x0: x, x1: p.x + p.w, anchored: true });
  }
}

function layerNumber(v) {
  const n = Number(v);
  if (Number.isFinite(n)) return n;
  const t = Date.parse(v);
  return Number.isFinite(t) ? t : NaN;
}

function oscillatorLabel(layer) {
  if (layer.id) return layer.id;
  if (layer.kind === "rsi") return "RSI";
  if (layer.kind === "macd") return "MACD";
  if (layer.kind === "stochastic") return "Stoch";
  return layer.kind;
}

function oscillatorRange(series, keys, fallback) {
  let yMin = Number(series && series.y_min);
  let yMax = Number(series && series.y_max);
  const explicitRange = Number.isFinite(yMin) && Number.isFinite(yMax) && yMin !== yMax;
  if (!explicitRange) {
    yMin = Infinity;
    yMax = -Infinity;
    for (const key of keys) {
      const arr = Array.isArray(series && series[key]) ? series[key] : [];
      for (const raw of arr) {
        const v = Number(raw);
        if (!Number.isFinite(v)) continue;
        yMin = Math.min(yMin, v);
        yMax = Math.max(yMax, v);
      }
    }
    if (!Number.isFinite(yMin) || !Number.isFinite(yMax)) {
      yMin = fallback[0];
      yMax = fallback[1];
    }
  }
  if (yMin === yMax) {
    const pad = Math.abs(yMin) * 0.05 || 1;
    yMin -= pad;
    yMax += pad;
  }
  if (explicitRange) return [yMin, yMax];
  const pad = Math.max((yMax - yMin) * 0.05, 1e-9);
  return [yMin - pad, yMax + pad];
}

function paneY(pane, value, yMin, yMax) {
  return pane.y + (1 - (value - yMin) / (yMax - yMin)) * pane.h;
}

function paneSlotWidth(view, pane, xs, i, visibleCount) {
  const x = layerNumber(xs[i]);
  const prev = i > 0 ? layerNumber(xs[i - 1]) : NaN;
  const next = i < xs.length - 1 ? layerNumber(xs[i + 1]) : NaN;
  let left = Number.isFinite(prev)
    ? Math.abs(view._dataToScreenX(x) - view._dataToScreenX(prev))
    : NaN;
  let right = Number.isFinite(next)
    ? Math.abs(view._dataToScreenX(next) - view._dataToScreenX(x))
    : NaN;
  const slot = Math.min(
    Number.isFinite(left) && left > 0 ? left : Infinity,
    Number.isFinite(right) && right > 0 ? right : Infinity
  );
  if (Number.isFinite(slot)) return Math.max(1, Math.min(12, slot * 0.68));
  return Math.max(1, Math.min(10, (pane.w / Math.max(visibleCount, 1)) * 0.68));
}

function drawPaneFrame(view, ctx, layer, pane, yMin, yMax, label) {
  const guides = Array.isArray(layer.props && layer.props.series && layer.props.series.guides)
    ? layer.props.series.guides
    : [];
  const gridColor = view._layerColor(layer, "grid_color", [0.56, 0.64, 0.76, 1]);
  const labelColor = rgba(view._layerColor(layer, "label_color", [0.32, 0.37, 0.46, 1]), 0.86);
  ctx.save();
  ctx.fillStyle = "rgba(128,128,128,.026)";
  ctx.fillRect(pane.x, pane.y, pane.w, pane.h);
  ctx.strokeStyle = rgba(gridColor, 0.20);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pane.x, Math.round(pane.y) + 0.5);
  ctx.lineTo(pane.x + pane.w, Math.round(pane.y) + 0.5);
  for (const raw of guides) {
    const g = Number(raw);
    if (!Number.isFinite(g) || g < yMin || g > yMax) continue;
    const y = Math.round(paneY(pane, g, yMin, yMax)) + 0.5;
    ctx.moveTo(pane.x, y);
    ctx.lineTo(pane.x + pane.w, y);
  }
  ctx.stroke();
  ctx.fillStyle = labelColor;
  ctx.font = "11px system-ui,sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(label, pane.x + 4, pane.y + 13);
  ctx.textAlign = "right";
  ctx.fillText(fmtLinear(yMax, Math.max((yMax - yMin) / 2, 1)), pane.x + pane.w - 4, pane.y + 13);
  ctx.fillText(fmtLinear(yMin, Math.max((yMax - yMin) / 2, 1)), pane.x + pane.w - 4, pane.y + pane.h - 4);
  ctx.restore();
}

function drawPaneLine(view, ctx, pane, xs, values, yMin, yMax, color, width = 1.35) {
  if (!Array.isArray(xs) || !Array.isArray(values) || xs.length < 2 || values.length < 2) return;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  let started = false;
  const n = Math.min(xs.length, values.length);
  for (let i = 0; i < n; i++) {
    const x = view._dataToScreenX(layerNumber(xs[i]));
    const value = Number(values[i]);
    if (!Number.isFinite(x) || !Number.isFinite(value)) {
      started = false;
      continue;
    }
    const y = paneY(pane, value, yMin, yMax);
    if (started) ctx.lineTo(x, y);
    else {
      ctx.moveTo(x, y);
      started = true;
    }
  }
  ctx.stroke();
  ctx.restore();
}

function drawMacdHistogram(view, ctx, layer, pane, series, yMin, yMax) {
  const xs = Array.isArray(series.x) ? series.x : [];
  const hist = Array.isArray(series.histogram) ? series.histogram : [];
  if (!xs.length || !hist.length) return;
  const upColor = view._layerColor(layer, "histogram_positive_color", [0.13, 0.67, 0.58, 1]);
  const downColor = view._layerColor(layer, "histogram_negative_color", [0.95, 0.21, 0.27, 1]);
  const zero = paneY(pane, 0, yMin, yMax);
  let visible = 0;
  for (let i = 0; i < Math.min(xs.length, hist.length); i++) {
    const x = layerNumber(xs[i]);
    const h = Number(hist[i]);
    if (Number.isFinite(x) && Number.isFinite(h) && x >= view.view.x0 && x <= view.view.x1) visible++;
  }
  ctx.save();
  for (let i = 0; i < Math.min(xs.length, hist.length); i++) {
    const x = view._dataToScreenX(layerNumber(xs[i]));
    const h = Number(hist[i]);
    if (!Number.isFinite(x) || !Number.isFinite(h)) continue;
    const y = paneY(pane, h, yMin, yMax);
    const w = paneSlotWidth(view, pane, xs, i, visible);
    const top = Math.min(y, zero);
    const height = Math.max(1, Math.abs(y - zero));
    ctx.fillStyle = rgba(h >= 0 ? upColor : downColor, 0.42);
    ctx.fillRect(x - w / 2, top, w, height);
  }
  ctx.restore();
}

function drawPaneFilledLine(view, ctx, pane, xs, values, yMin, yMax, lineColor, fillColor, baseline = 0) {
  if (!Array.isArray(xs) || !Array.isArray(values) || xs.length < 2 || values.length < 2) return;
  const zero = paneY(pane, Math.max(yMin, Math.min(yMax, baseline)), yMin, yMax);
  const pts = [];
  const n = Math.min(xs.length, values.length);
  for (let i = 0; i < n; i++) {
    const x = view._dataToScreenX(layerNumber(xs[i]));
    const value = Number(values[i]);
    if (!Number.isFinite(x) || !Number.isFinite(value)) continue;
    pts.push([x, paneY(pane, value, yMin, yMax)]);
  }
  if (pts.length < 2) return;
  ctx.save();
  ctx.fillStyle = fillColor;
  ctx.beginPath();
  ctx.moveTo(pts[0][0], zero);
  for (const [x, y] of pts) ctx.lineTo(x, y);
  ctx.lineTo(pts[pts.length - 1][0], zero);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = lineColor;
  ctx.lineWidth = 1.25;
  ctx.beginPath();
  pts.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
  ctx.stroke();
  ctx.restore();
}

function drawPerformancePane(view, ctx, layer) {
  const pane = view._oscillatorPaneFor(layer);
  const series = layer.props && layer.props.series;
  if (!pane || !series || !Array.isArray(series.x)) return;
  const [yMin, yMax] = oscillatorRange(series, ["drawdown_y"], [-1, 0]);
  const label = series.drawdown_mode === "absolute" ? "Drawdown" : "Drawdown %";
  drawPaneFrame(view, ctx, layer, pane, yMin, yMax, label);
  const color = view._layerColor(layer, "drawdown_color", [0.95, 0.21, 0.27, 1]);
  drawPaneFilledLine(
    view,
    ctx,
    pane,
    series.x,
    series.drawdown_y,
    yMin,
    yMax,
    rgba(color, 0.92),
    rgba(color, 0.20),
    0
  );
}

function drawReturnsDistribution(view, ctx, layer) {
  const series = layer.props && layer.props.series;
  if (!series || !Array.isArray(series.bin_edges) || !Array.isArray(series.y)) return;
  const edges = series.bin_edges;
  const y = series.y;
  if (edges.length < 2 || !y.length) return;
  const p = view.plot;
  const barColor = view._layerColor(layer, "bar_color", [0.20, 0.40, 0.78, 1]);
  const markerColor = view._layerColor(layer, "marker_color", [0.86, 0.19, 0.22, 1]);
  ctx.save();
  ctx.fillStyle = rgba(barColor, Number(layer.style && layer.style.opacity) || 0.62);
  ctx.strokeStyle = rgba(barColor, 0.88);
  ctx.lineWidth = 1;
  for (let i = 0; i < Math.min(y.length, edges.length - 1); i++) {
    const x0 = view._dataToScreenX(Number(edges[i]));
    const x1 = view._dataToScreenX(Number(edges[i + 1]));
    const v = Number(y[i]);
    if (!Number.isFinite(x0) || !Number.isFinite(x1) || !Number.isFinite(v) || v < 0) continue;
    const left = Math.min(x0, x1) + 1;
    const right = Math.max(x0, x1) - 1;
    const top = view._dataToScreenY(v);
    const base = view._dataToScreenY(0);
    const w = Math.max(1, right - left);
    const h = Math.max(1, base - top);
    ctx.fillRect(left, top, w, h);
    ctx.strokeRect(left, top, w, h);
  }
  ctx.restore();

  const markers = Array.isArray(series.markers) ? series.markers : [];
  for (const marker of markers) {
    const x = view._dataToScreenX(Number(marker.x));
    if (!Number.isFinite(x)) continue;
    drawLine(ctx, x, p.y, x, p.y + p.h, rgba(markerColor, 0.92), 1.25, [5, 4]);
    drawLabel(ctx, marker.label || marker.role || "risk", x + 6, p.y + 18, "#fff", rgba(markerColor, 0.92));
  }
}

function drawOscillatorPane(view, ctx, layer) {
  const pane = view._oscillatorPaneFor(layer);
  const series = layer.props && layer.props.series;
  if (!pane || !series || !Array.isArray(series.x)) return;
  if (layer.kind === "rsi") {
    const [yMin, yMax] = oscillatorRange(series, ["rsi"], [0, 100]);
    drawPaneFrame(view, ctx, layer, pane, yMin, yMax, oscillatorLabel(layer));
    const color = rgba(view._layerColor(layer, "color", [0.25, 0.46, 0.95, 1]), 0.98);
    drawPaneLine(view, ctx, pane, series.x, series.rsi, yMin, yMax, color, Number(layer.style && layer.style.width) || 1.35);
    return;
  }
  if (layer.kind === "macd") {
    const [yMin, yMax] = oscillatorRange(series, ["macd", "signal", "histogram"], [-1, 1]);
    drawPaneFrame(view, ctx, layer, pane, yMin, yMax, oscillatorLabel(layer));
    drawMacdHistogram(view, ctx, layer, pane, series, yMin, yMax);
    const macdColor = rgba(view._layerColor(layer, "color", [0.25, 0.46, 0.95, 1]), 0.98);
    const signalColor = rgba(view._layerColor(layer, "signal_color", [0.96, 0.62, 0.04, 1]), 0.96);
    drawPaneLine(view, ctx, pane, series.x, series.macd, yMin, yMax, macdColor, Number(layer.style && layer.style.width) || 1.25);
    drawPaneLine(view, ctx, pane, series.x, series.signal, yMin, yMax, signalColor, Number(layer.style && layer.style.signal_width) || 1.15);
    return;
  }
  if (layer.kind === "stochastic") {
    const [yMin, yMax] = oscillatorRange(series, ["k", "d"], [0, 100]);
    drawPaneFrame(view, ctx, layer, pane, yMin, yMax, oscillatorLabel(layer));
    const kColor = rgba(view._layerColor(layer, "color", [0.25, 0.46, 0.95, 1]), 0.98);
    const dColor = rgba(view._layerColor(layer, "signal_color", [0.96, 0.62, 0.04, 1]), 0.96);
    drawPaneLine(view, ctx, pane, series.x, series.k, yMin, yMax, kColor, Number(layer.style && layer.style.width) || 1.25);
    drawPaneLine(view, ctx, pane, series.x, series.d, yMin, yMax, dColor, Number(layer.style && layer.style.signal_width) || 1.15);
  }
}

function patternSlotWidth(xs, i) {
  if (xs.length <= 1) return 7;
  const prev = i > 0 ? xs[i] - xs[i - 1] : xs[1] - xs[0];
  const next = i < xs.length - 1 ? xs[i + 1] - xs[i] : prev;
  const slot = Math.min(Math.abs(prev), Math.abs(next));
  return Math.max(3, Math.min(18, slot * 0.62));
}

function drawBarsPattern(view, ctx, layer) {
  const props = layer.props || {};
  const pattern = props.pattern;
  if (!pattern || !Array.isArray(pattern.x) || !pattern.x.length) {
    drawRangeStudy(view, ctx, layer);
    return;
  }
  const xs = pattern.x.map((v) => view._dataToScreenX(layerNumber(v)));
  const open = pattern.open || [];
  const high = pattern.high || [];
  const low = pattern.low || [];
  const close = pattern.close || [];
  const color = view._layerColor(layer, "color", [0.56, 0.64, 0.76, 1]);
  const upColor = view._layerColor(layer, "up_color", [0.13, 0.67, 0.58, 1]);
  const downColor = view._layerColor(layer, "down_color", [0.95, 0.21, 0.27, 1]);
  const wickColor = view._layerColor(layer, "wick_color", [0.58, 0.65, 0.76, 1]);
  const mode = props.mode || "candlestick";
  const p = view.plot;

  ctx.save();
  ctx.globalAlpha = Number(layer.style && layer.style.opacity) || 0.74;
  ctx.strokeStyle = rgba(color, 0.55);
  ctx.setLineDash([4, 4]);
  ctx.lineWidth = 1;
  const firstX = xs.find((x) => Number.isFinite(x));
  if (Number.isFinite(firstX)) {
    ctx.beginPath();
    ctx.moveTo(firstX, p.y);
    ctx.lineTo(firstX, p.y + p.h);
    ctx.stroke();
  }
  ctx.setLineDash([]);

  if (mode === "line") {
    ctx.strokeStyle = rgba(color, 0.95);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < xs.length; i++) {
      const x = xs[i];
      const y = view._dataToScreenY(Number(close[i]));
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      if (started) ctx.lineTo(x, y);
      else {
        ctx.moveTo(x, y);
        started = true;
      }
    }
    ctx.stroke();
  } else {
    for (let i = 0; i < xs.length; i++) {
      const x = xs[i];
      const o = Number(open[i]);
      const h = Number(high[i]);
      const l = Number(low[i]);
      const c = Number(close[i]);
      if (![x, o, h, l, c].every(Number.isFinite)) continue;
      const yo = view._dataToScreenY(o);
      const yh = view._dataToScreenY(h);
      const yl = view._dataToScreenY(l);
      const yc = view._dataToScreenY(c);
      const up = c >= o;
      const w = patternSlotWidth(xs, i);
      ctx.strokeStyle = rgba(wickColor, 0.82);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, yh);
      ctx.lineTo(x, yl);
      ctx.stroke();
      const bodyTop = Math.min(yo, yc);
      const bodyH = Math.max(1, Math.abs(yc - yo));
      if (mode === "ohlc") {
        const col = up ? upColor : downColor;
        ctx.strokeStyle = rgba(col, 0.95);
        ctx.beginPath();
        ctx.moveTo(x - w / 2, yo);
        ctx.lineTo(x, yo);
        ctx.moveTo(x, yc);
        ctx.lineTo(x + w / 2, yc);
        ctx.stroke();
      } else if (up) {
        ctx.fillStyle = "rgba(13,17,26,.78)";
        ctx.strokeStyle = rgba(upColor, 0.95);
        ctx.fillRect(x - w / 2, bodyTop, w, bodyH);
        ctx.strokeRect(x - w / 2, bodyTop, w, bodyH);
      } else {
        ctx.fillStyle = rgba(downColor, 0.82);
        ctx.strokeStyle = rgba(downColor, 0.95);
        ctx.fillRect(x - w / 2, bodyTop, w, bodyH);
        ctx.strokeRect(x - w / 2, bodyTop, w, bodyH);
      }
    }
  }
  ctx.restore();

  const anchor = layerAnchor(view, layer, "destination");
  const labelX = finitePoint(anchor) ? view._dataToScreenX(anchor.x) + 6 : (firstX || p.x) + 6;
  const labelY = finitePoint(anchor) ? view._dataToScreenY(anchor.y) - 18 : p.y + 28;
  drawLabel(ctx, "Bars pattern", labelX, labelY, "#fff", rgba(color, 0.78));
}

function drawRangeStudy(view, ctx, layer) {
  const start = layerAnchor(view, layer, "start");
  const end = layerAnchor(view, layer, "end");
  if (!start || !end || !Number.isFinite(start.x) || !Number.isFinite(end.x)) return;
  const p = view.plot;
  const x0 = view._dataToScreenX(start.x);
  const x1 = view._dataToScreenX(end.x);
  const color = view._layerColor(layer, "color", [0.56, 0.64, 0.76, 1]);
  ctx.save();
  ctx.fillStyle = rgba(color, 0.08);
  ctx.fillRect(Math.min(x0, x1), p.y, Math.abs(x1 - x0), p.h);
  ctx.restore();
  drawLine(ctx, x0, p.y, x0, p.y + p.h, rgba(color, 0.9), 1, [4, 4]);
  drawLine(ctx, x1, p.y, x1, p.y + p.h, rgba(color, 0.9), 1, [4, 4]);
  if (layer.kind === "fixed_range_volume_profile") {
    drawVolumeProfile(view, ctx, layer, { x0, x1 });
  }
  drawLabel(ctx, layer.kind === "fixed_range_volume_profile" ? "FRVP" : "Range", Math.max(x0, x1) + 6, p.y + 16, "#fff");
}

function drawPattern(view, ctx, layer) {
  const labels = layer.kind === "xabcd_pattern" ? "XABCD" : "ABCD";
  const pts = [];
  for (const label of labels) {
    const p = layerAnchor(view, layer, label);
    if (!finitePoint(p)) return;
    pts.push({ label, x: view._dataToScreenX(p.x), y: view._dataToScreenY(p.y) });
  }
  const color = rgba(view._layerColor(layer, "color", [0.64, 0.45, 0.95, 1]), 1);
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = "rgba(126,87,194,.10)";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  pts.forEach((p, i) => i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y));
  ctx.stroke();
  if (pts.length > 3) {
    ctx.lineTo(pts[0].x, pts[0].y);
    ctx.fill();
  }
  ctx.restore();
  for (const p of pts) {
    drawHandle(ctx, p.x, p.y, color);
    drawLabel(ctx, p.label, p.x + 6, p.y - 8, "#fff");
  }
}

function drawGhostFeed(view, ctx, layer) {
  const anchor = layerAnchor(view, layer, "anchor");
  if (!finitePoint(anchor)) return;
  const p = view.plot;
  const props = layer.props || {};
  const feed = props.feed;
  if (feed && Array.isArray(feed.x) && feed.x.length) {
    const xs = feed.x.map((v) => view._dataToScreenX(layerNumber(v)));
    const open = feed.open || [];
    const high = feed.high || [];
    const low = feed.low || [];
    const close = feed.close || [];
    const color = view._layerColor(layer, "color", [0.58, 0.67, 0.8, 1]);
    const upColor = view._layerColor(layer, "up_color", [0.56, 0.72, 0.86, 1]);
    const downColor = view._layerColor(layer, "down_color", [0.84, 0.48, 0.57, 1]);
    const wickColor = view._layerColor(layer, "wick_color", [0.58, 0.67, 0.8, 1]);
    ctx.save();
    ctx.globalAlpha = Number(layer.style && layer.style.opacity) || 0.42;
    ctx.strokeStyle = rgba(color, 0.78);
    ctx.setLineDash([5, 4]);
    ctx.lineWidth = 1;
    const firstX = xs.find((x) => Number.isFinite(x));
    if (Number.isFinite(firstX)) {
      ctx.beginPath();
      ctx.moveTo(firstX, p.y);
      ctx.lineTo(firstX, p.y + p.h);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    for (let i = 0; i < xs.length; i++) {
      const x = xs[i];
      const o = Number(open[i]);
      const h = Number(high[i]);
      const l = Number(low[i]);
      const c = Number(close[i]);
      if (![x, o, h, l, c].every(Number.isFinite)) continue;
      const yo = view._dataToScreenY(o);
      const yh = view._dataToScreenY(h);
      const yl = view._dataToScreenY(l);
      const yc = view._dataToScreenY(c);
      const up = c >= o;
      const w = patternSlotWidth(xs, i);
      ctx.strokeStyle = rgba(wickColor, 0.78);
      ctx.beginPath();
      ctx.moveTo(x, yh);
      ctx.lineTo(x, yl);
      ctx.stroke();
      const bodyTop = Math.min(yo, yc);
      const bodyH = Math.max(1, Math.abs(yc - yo));
      const bodyColor = up ? upColor : downColor;
      ctx.fillStyle = up ? rgba(bodyColor, 0.20) : rgba(bodyColor, 0.36);
      ctx.strokeStyle = rgba(bodyColor, 0.82);
      ctx.fillRect(x - w / 2, bodyTop, w, bodyH);
      ctx.strokeRect(x - w / 2, bodyTop, w, bodyH);
    }
    ctx.restore();
    drawLabel(ctx, "Ghost feed", view._dataToScreenX(anchor.x) + 6, view._dataToScreenY(anchor.y) - 18, "#fff", rgba(color, 0.72));
    return;
  }
  const bars = Math.min(48, Math.max(1, Number(props.bars || 12)));
  const dx = Math.max(5, p.w / 80);
  const dir = props.direction === "down" ? 1 : -1;
  const color = view._layerColor(layer, "color", [0.58, 0.67, 0.8, 1]);
  let x = view._dataToScreenX(anchor.x);
  let y = view._dataToScreenY(anchor.y);
  ctx.save();
  ctx.strokeStyle = rgba(color, 0.55);
  ctx.fillStyle = rgba(color, 0.16);
  ctx.lineWidth = 1;
  for (let i = 0; i < bars; i++) {
    const bodyH = 8 + (i % 5);
    const wickH = bodyH + 8;
    const cx = x + (i + 1) * dx;
    const cy = y + dir * i * 1.8 + Math.sin(i * 0.8) * 6;
    ctx.beginPath();
    ctx.moveTo(cx, cy - wickH / 2);
    ctx.lineTo(cx, cy + wickH / 2);
    ctx.stroke();
    ctx.fillRect(cx - 2.5, cy - bodyH / 2, 5, bodyH);
    ctx.strokeRect(cx - 2.5, cy - bodyH / 2, 5, bodyH);
  }
  ctx.restore();
  drawLabel(ctx, "Ghost feed", x + dx, y - 18, "#fff");
}

const LAYER_KINDS = {
  position: { draw: drawPosition },
  long_position: { draw: drawPosition },
  short_position: { draw: drawPosition },
  position_forecast: { draw: drawProjection },
  sector: { draw: drawSector },
  anchored_vwap: { draw: drawAnchoredStudy },
  vwap: { draw: () => {} },
  bollinger_bands: { draw: () => {} },
  anchored_volume_profile: { draw: drawAnchoredStudy },
  fixed_range_volume_profile: { draw: drawRangeStudy },
  price_range: { draw: drawRangeStudy },
  date_range: { draw: drawRangeStudy },
  date_price_range: { draw: drawRangeStudy },
  bars_pattern: { draw: drawBarsPattern },
  ghost_feed: { draw: drawGhostFeed },
  abcd_pattern: { draw: drawPattern },
  xabcd_pattern: { draw: drawPattern },
  volume_bars: { draw: drawVolumeBars },
  equity_drawdown: { draw: drawPerformancePane },
  rsi: { draw: drawOscillatorPane },
  macd: { draw: drawOscillatorPane },
  stochastic: { draw: drawOscillatorPane },
  moving_average: { draw: () => {} },
  returns_distribution: { draw: drawReturnsDistribution },
};

function layerOf(kind) {
  return LAYER_KINDS[kind] || { draw: () => {} };
}
