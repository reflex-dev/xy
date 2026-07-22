import { fmtCategory, fmtNumberSpec, fmtValue } from "./30_ticks";
import { ChartView } from "./50_chartview";

// ChartView tooltip resolution: map a hovered vertex back to its source
// row, denormalize units, and compose the tooltip lines/DOM. Split out of
// 50_chartview.js; augments the prototype so `this.*` is unchanged.

Object.assign(ChartView.prototype, {
  _showTooltip(hit, clientX, clientY) {
    const row = this._localRow(hit);
    this._lastRow = row;
    this._setTooltipAnchor(hit, row, clientX, clientY);
    this._renderTooltip(row, clientX, clientY);
    if (this._interactionFlag("hover")) {
      // Existing row/trace/index/view keys stay; the §7.1 structured payload
      // (active/cursor/points) is genuinely additive on the same detail.
      this._dispatchChartEvent("hover", {
        row,
        trace: hit.trace,
        index: hit.index,
        view: this._eventView("hover"),
        ...this._hoverPayload(row, hit, clientX, clientY),
      });
    }
    if (this.comm) {
      // Exact f64 values from the kernel canonical store (§16). The local row
      // (decoded from f32) shows instantly; the exact one replaces it.
      // NOTE: picks use their own sequence — sharing this.seq with view
      // requests made a hover invalidate an in-flight tier_update, freezing
      // the stale tier (found in staff review).
      this._pickSeq = (this._pickSeq || 0) + 1;
      const req: any = { type: "pick", seq: this._pickSeq, trace: hit.trace, index: hit.index };
      // Drilled picks name the subset version they hit against; the kernel
      // returns None instead of translating through the wrong subset (§16/§17).
      const hg = hit.g;
      if (hg && hg.tier === "density" && hg.drill && hg.drill.seq !== undefined) {
        req.drill_seq = hg.drill.seq;
      }
      this.comm.send(req);
    }
  },

  _localRow(hit) {
    // Approximate readout from the resident f32 (used in standalone export and
    // as the instant value before the kernel's exact reply, §37). Only present
    // when CPU copies were retained (renderStandalone); the widget path replaces
    // this with the kernel's exact f64 row (§16).
    const g = hit.g;
    const cpu = g._cpu;
    const row: any = { trace: g.trace.id, index: hit.index };
    if (hit.heatmap && g.heatmap && g._cpuHeatmap) {
      const h = g.heatmap;
      const { row: heatRow, col } = hit.heatmap;
      const rawX = h.xRange[0] + (col + 0.5) * ((h.xRange[1] - h.xRange[0]) / h.w);
      const rawY = h.yRange[0] + (heatRow + 0.5) * ((h.yRange[1] - h.yRange[0]) / h.h);
      const [x, xKind] = this._sourceDisplayValue(g, "x", rawX, "float");
      const [y, yKind] = this._sourceDisplayValue(g, "y", rawY, "float");
      row.x = x;
      row.y = y;
      if (xKind !== undefined) row.x_kind = xKind;
      if (yKind !== undefined) row.y_kind = yKind;
      const norm = g._cpuHeatmap.grid[hit.index];
      row.color_value = this._channelDisplayValue(norm, g.trace.color);
    } else if (g._cpuRect) {
      const r = g._cpuRect;
      const x0 = this._decodeValue(r.x0, r.x0Meta, hit.index);
      const x1 = this._decodeValue(r.x1, r.x1Meta, hit.index);
      const y0 = this._decodeValue(r.y0, r.y0Meta, hit.index);
      const y1 = this._decodeValue(r.y1, r.y1Meta, hit.index);
      const [x, xKind] = this._sourceDisplayValue(
        g, "x", x0 + (x1 - x0) / 2, r.x0Meta.kind,
      );
      const [y, yKind] = this._sourceDisplayValue(g, "y", y1, r.y1Meta.kind);
      row.x = x;
      row.y = y;
      if (xKind !== undefined) row.x_kind = xKind;
      if (yKind !== undefined) row.y_kind = yKind;
    } else if (cpu) {
      const xMeta = cpu.xMeta || g.xMeta;
      const yMeta = cpu.yMeta || g.yMeta;
      const rawX = this._decodeValue(cpu.x, xMeta, hit.index);
      const rawY = this._decodeValue(cpu.y, yMeta, hit.index);
      const [x, xKind] = this._sourceDisplayValue(g, "x", rawX, xMeta && xMeta.kind);
      const [y, yKind] = this._sourceDisplayValue(g, "y", rawY, yMeta && yMeta.kind);
      row.x = x;
      row.y = y;
      if (xKind !== undefined) row.x_kind = xKind;
      if (yKind !== undefined) row.y_kind = yKind;
      const color = g.trace.color;
      if (cpu.color && color) {
        if (color.mode === "categorical" && Array.isArray(color.categories)) {
          const code = Math.round(cpu.color[hit.index]);
          if (code >= 0 && code < color.categories.length) {
            row.color_category = String(color.categories[code]);
          }
        } else if (color.mode === "continuous") {
          row.color_value = this._channelDisplayValue(cpu.color[hit.index], color);
        }
      }
      const size = g.trace.size;
      if (cpu.size && size && size.mode === "continuous") {
        row.size_value = this._channelDisplayValue(cpu.size[hit.index], size);
      }
    }
    this._applySharedTooltipFields(row);
    return row;
  },

  _sourceDisplayValue(g, channel, value, kind) {
    const axis = channel === "x" ? this._axis(g && g.xAxis) : this._axis(g && g.yAxis);
    if (channel === "x" && axis.kind === "category") {
      return [fmtCategory(value, axis.categories || []), undefined];
    }
    if (channel === "y" && axis.kind === "category") {
      return [fmtCategory(value, axis.categories || []), undefined];
    }
    return [value, kind];
  },

  _sourceValue(g, source, index) {
    if (!g || index < 0) return [undefined, undefined];
    const channel = source.channel;
    if (channel === "x" || channel === "y") {
      const cpu = g._cpu;
      if (!cpu || !cpu[channel]) return [undefined, undefined];
      const meta = channel === "x" ? (cpu.xMeta || g.xMeta) : (cpu.yMeta || g.yMeta);
      const value = this._decodeValue(cpu[channel], meta, index);
      if (!Number.isFinite(value)) return [undefined, undefined];
      return this._sourceDisplayValue(g, channel, value, meta && meta.kind);
    }
    if (channel === "color_value") {
      if (g._cpuHeatmap && g._cpuHeatmap.grid && g.trace.color) {
        return [this._channelDisplayValue(g._cpuHeatmap.grid[index], g.trace.color), undefined];
      }
      if (g._cpu && g._cpu.color && g.trace.color) {
        return [this._channelDisplayValue(g._cpu.color[index], g.trace.color), undefined];
      }
    }
    if (channel === "color_category" && g._cpu && g._cpu.color && g.trace.color) {
      const code = Math.round(g._cpu.color[index]);
      const categories = g.trace.color.categories || [];
      if (code >= 0 && code < categories.length) return [String(categories[code]), undefined];
    }
    if (channel === "size_value" && g._cpu && g._cpu.size && g.trace.size) {
      return [this._channelDisplayValue(g._cpu.size[index], g.trace.size), undefined];
    }
    return [undefined, undefined];
  },

  _applySharedTooltipFields(row) {
    const sources = this.spec.tooltip && this.spec.tooltip.sources;
    if (!sources || typeof sources !== "object" || row.x === undefined) return;
    for (const [field, entries] of Object.entries(sources)) {
      if (!Array.isArray(entries) || row[field] !== undefined) continue;
      const source = entries.find((entry) => entry.trace === row.trace) || entries[0];
      if (!source || !Number.isFinite(Number(source.trace))) continue;
      const g = this.gpuTraces.find((trace) => trace.trace.id === source.trace);
      if (!g) continue;
      let idx = Number.isInteger(row.index) && source.trace === row.trace ? row.index : -1;
      if (
        !g._cpuHeatmap &&
        (idx < 0 || !g._cpu || !g._cpu.x || idx >= g._cpu.x.length)
      ) {
        idx = this._nearestCpuIndex(g, row.x);
      }
      const [value, kind] = this._sourceValue(g, source, idx);
      if (value === undefined) continue;
      row[field] = value;
      if (kind !== undefined) row[`${field}_kind`] = kind;
    }
  },

  // Shipped-value → display-value for a continuous channel: raw-encoded
  // buffers already hold data units (wire-protocol §3); unit-encoded ones
  // (legacy, heatmap grids, f32 fallback) denormalize over the spec domain.
  _channelDisplayValue(value, spec) {
    if (spec && spec.enc === "raw") {
      const v = Number(value);
      return v;
    }
    return this._denormalizeUnit(value, spec && spec.domain);
  },

  _denormalizeUnit(value, domain) {
    const v = Number(value);
    if (!Number.isFinite(v)) return v;
    if (!Array.isArray(domain) || domain.length < 2) return v;
    const lo = Number(domain[0]);
    const hi = Number(domain[1]);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return v;
    return lo + v * (hi - lo);
  },

  _defaultTooltipLines(row) {
    const lines = [];
    if (row.x !== undefined) lines.push(`x: ${fmtValue(row.x, row.x_kind)}`);
    if (row.y !== undefined) lines.push(`y: ${fmtValue(row.y, row.y_kind)}`);
    if (row.color_value !== undefined) lines.push(`color: ${fmtValue(row.color_value)}`);
    if (row.color_category !== undefined) lines.push(`${row.color_category}`);
    if (row.size_value !== undefined) lines.push(`size: ${fmtValue(row.size_value)}`);
    if (!lines.length) lines.push(`#${row.index}`);
    return lines;
  },

  _tooltipLookup(row, field) {
    const aliases = (this.spec.tooltip && this.spec.tooltip.aliases) || {};
    const key = row[field] !== undefined ? field : aliases[field];
    if (!key || row[key] === undefined) return [undefined, undefined];
    return [row[key], row[`${key}_kind`]];
  },

  _formatTooltipValue(value, kind, format) {
    const formatted = fmtNumberSpec(value, format);
    if (formatted !== null) return formatted;
    return fmtValue(value, kind);
  },

  _tooltipLines(row) {
    const tooltip = this.spec.tooltip || {};
    if (!tooltip.title && !Array.isArray(tooltip.fields)) return this._defaultTooltipLines(row);
    const formats = tooltip.format || {};
    const lines = [];
    if (typeof tooltip.title === "string") {
      const title = tooltip.title.replace(/\{([^}]+)\}/g, (_, field) => {
        const [value, kind] = this._tooltipLookup(row, field);
        return value === undefined ? "" : this._formatTooltipValue(value, kind, formats[field]);
      });
      if (title) lines.push(title);
    }
    if (Array.isArray(tooltip.fields)) {
      for (const field of tooltip.fields) {
        if (typeof field !== "string") continue;
        const [value, kind] = this._tooltipLookup(row, field);
        if (value === undefined) continue;
        lines.push(`${field}: ${this._formatTooltipValue(value, kind, formats[field])}`);
      }
    }
    return lines.length ? lines : this._defaultTooltipLines(row);
  },

  // Anchor in data space so view changes carry the tooltip with its point.
  _setTooltipAnchor(hit, row, clientX, clientY) {
    const g = hit.g;
    if (!g) { this._tooltipAnchor = null; return; }
    const xAxis = g.xAxis || "x";
    const yAxis = g.yAxis || "y";
    let x = row.x;
    let y = row.y;
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      // Category rows carry labels, so derive their numeric anchor from the pick.
      const rect = this.canvas.getBoundingClientRect();
      [x, y] = this._dataFromCanvas(clientX - rect.left, clientY - rect.top, xAxis, yAxis);
    }
    this._tooltipAnchor = Number.isFinite(x) && Number.isFinite(y)
      ? { xAxis, yAxis, x, y }
      : null;
    // Keyboard traversal can reach an off-screen point; keep its clamped placement.
    if (this._tooltipAnchor && !this._tooltipAnchorPx()) this._tooltipAnchor = null;
  },

  _tooltipAnchorPx() {
    const a = this._tooltipAnchor;
    if (!a) return null;
    const lx = this._dataPx(a.xAxis, a.x);
    const ly = this._dataPx(a.yAxis, a.y);
    const p = this.plot;
    if (!Number.isFinite(lx) || !Number.isFinite(ly)
        || lx < p.x || lx > p.x + p.w || ly < p.y || ly > p.y + p.h) {
      return null;
    }
    return { lx, ly };
  },

  _hideTooltip() {
    this.tooltip.style.display = "none";
    this._tooltipAnchor = null;
  },

  // A hidden retained anchor is off-screen and may return after another draw.
  _repositionTooltip() {
    if (!this._tooltipAnchor) return;
    const pos = this._tooltipAnchorPx();
    if (!pos) {
      this.tooltip.style.display = "none";
      return;
    }
    this.tooltip.style.display = "block";
    this._placeTooltip(pos.lx, pos.ly);
  },

  _placeTooltip(lx, ly) {
    const tw = this.tooltip.offsetWidth;
    const th = this.tooltip.offsetHeight;
    const edge = 4;
    const gap = 12;
    const maxLeft = Math.max(edge, this.size.w - tw - edge);
    const left = Math.max(edge, Math.min(lx + gap, maxLeft));
    const below = ly + gap;
    const above = ly - th - gap;
    const top = below + th <= this.size.h - edge ? below : Math.max(edge, above);
    this.tooltip.style.left = left + "px";
    this.tooltip.style.top = top + "px";
  },

  _renderTooltip(row, clientX, clientY, options: any = {}) {
    if (!row || this.spec.show_tooltip === false) {
      this._hideTooltip();
      return;
    }
    const lines = this._tooltipLines(row);
    if (!this._customTooltip) {
      // Text nodes, not innerHTML: category labels are user data and must never
      // be parsed as markup (a category named "<img onerror=…>" is just a label).
      this.tooltip.textContent = "";
      lines.forEach((ln, i) => {
        if (i) this.tooltip.appendChild(document.createElement("br"));
        this.tooltip.appendChild(document.createTextNode(ln));
      });
    }
    if (this.a11yLive && options.announce !== false) {
      const prefix = this._a11yKeyboardReadout;
      const detail = lines.join(", ");
      const announcement = prefix
        ? `Point ${prefix.flat + 1} of ${prefix.total}. ${detail}`
        : detail;
      if (this.a11yLive.textContent !== announcement) this.a11yLive.textContent = announcement;
    }
    this.tooltip.style.display = "block";
    const pos = this._tooltipAnchorPx();
    if (pos) {
      this._placeTooltip(pos.lx, pos.ly);
    } else if (this._tooltipAnchor) {
      // Keep the content and anchor so zooming back can reveal the tooltip.
      this.tooltip.style.display = "none";
    } else {
      const rect = this.root.getBoundingClientRect();
      this._placeTooltip(clientX - rect.left, clientY - rect.top);
    }
  },
});
