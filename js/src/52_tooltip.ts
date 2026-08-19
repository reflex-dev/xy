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
      row.color_value = this._denormalizeUnit(norm, g.trace.color && g.trace.color.domain);
    } else if ((g._cpuRibbon || g._cpuFunnel) && Array.isArray(g.tooltipRows)) {
      // Semantic rows replace the coordinate readout: ribbon and funnel
      // geometry slots hold internal placement coordinates, and the pick
      // describes the flow/stage, never its placement.
      const semantic = g.tooltipRows[hit.index];
      if (semantic && typeof semantic === "object") Object.assign(row, semantic);
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
          row.color_value = this._denormalizeUnit(cpu.color[hit.index], color.domain);
        }
      }
      const size = g.trace.size;
      if (cpu.size && size && size.mode === "continuous") {
        row.size_value = this._denormalizeUnit(cpu.size[hit.index], size.domain);
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
        return [this._denormalizeUnit(g._cpuHeatmap.grid[index], g.trace.color.domain), undefined];
      }
      if (g._cpu && g._cpu.color && g.trace.color) {
        return [this._denormalizeUnit(g._cpu.color[index], g.trace.color.domain), undefined];
      }
    }
    if (channel === "color_category" && g._cpu && g._cpu.color && g.trace.color) {
      const code = Math.round(g._cpu.color[index]);
      const categories = g.trace.color.categories || [];
      if (code >= 0 && code < categories.length) return [String(categories[code]), undefined];
    }
    if (channel === "size_value" && g._cpu && g._cpu.size && g.trace.size) {
      return [this._denormalizeUnit(g._cpu.size[index], g.trace.size.domain), undefined];
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

  _denormalizeUnit(value, domain) {
    const v = Number(value);
    if (!Number.isFinite(v)) return v;
    if (!Array.isArray(domain) || domain.length < 2) return v;
    const lo = Number(domain[0]);
    const hi = Number(domain[1]);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return v;
    return lo + v * (hi - lo);
  },

  _defaultTooltipLabel(channel, fallback, labels, aliases) {
    for (const [field, alias] of Object.entries(aliases)) {
      if (alias === channel && typeof labels[field] === "string") {
        return { label: labels[field], customized: true };
      }
    }
    if (typeof labels[fallback] === "string") {
      return { label: labels[fallback], customized: true };
    }
    return { label: fallback, customized: false };
  },

  // The trace's own name, when it has one. The hover row carries `trace` (an
  // id), never the label, so the default readout used to identify a mark only
  // by its coordinates — on a pie that meant "x: 102.6, y: 0.94" for a slice
  // whose whole identity is "Cloudpeak $13B". Every other library leads its
  // tooltip with the series name; so does this one now.
  _tooltipSeriesName(row) {
    const traces = Array.isArray(this.spec.traces) ? this.spec.traces : [];
    const trace = traces.find((t) => t && t.id === row.trace);
    const name = trace && trace.name;
    return typeof name === "string" && name.trim() ? name : null;
  },

  // Under polar the two channels are not x and y, and saying so is actively
  // misleading: "x: 1.5708" on a radar names a spoke the chart labels "power".
  // More than that: the default readout shows VALUES, not angles — on most
  // polar charts the angle is where the layout put the mark, and the cursor
  // is already sitting on it. A numeric angle row is therefore OMITTED by
  // default; an authored spoke label (a radar category) survives because it
  // is a name, not an angle; and an explicit `labels={"x": ...}` opts the
  // angle row back in, formatted through the axis's own text function so
  // degrees keep their sign and radians read as pi-fractions.
  _polarTooltipField(channel, value, kind) {
    if (this.spec?.coords !== "polar") return null;
    const axis = this._axis(channel === "x" ? "x" : "y") || {};
    if (channel === "y") return { label: "r", value: fmtValue(value, kind) };
    // Authored spoke labels first, matched with tolerance. `_axisTickText`
    // compares tick values exactly, but the hovered angle arrives as decoded
    // offset-encoded f32 (§4/§16) while the tick was authored in f64 — so a
    // radar's pi/2 spoke missed its own label by ~1e-7 and fell back to
    // "1.57". The tolerance is relative to the spacing, so it can never reach
    // a neighbouring spoke.
    const values = Array.isArray(axis.tick_values) ? axis.tick_values : null;
    const texts = Array.isArray(axis.tick_labels) ? axis.tick_labels : null;
    if (values && texts) {
      let span = Infinity;
      for (let i = 1; i < values.length; i++) {
        span = Math.min(span, Math.abs(Number(values[i]) - Number(values[i - 1])));
      }
      const tol = Number.isFinite(span) ? span / 8 : 1e-6;
      for (let i = 0; i < values.length && i < texts.length; i++) {
        if (Math.abs(Number(values[i]) - Number(value)) <= tol) {
          return { label: "θ", value: String(texts[i]) };
        }
      }
    }
    const step = this._axisTicks?.("x", 6)?.step ?? 1;
    let text;
    try {
      text = this._axisTickText(axis, value, step);
    } catch {
      text = null;
    }
    return { label: "θ", value: text || fmtValue(value, kind), omit: true };
  },

  // A pie slice or a gauge band is one named wedge: the name IS the datum,
  // and theta/r are how the layout happened to place it — "Direct - 40%"
  // followed by "theta: 72, r: 1" answers a question nobody asked. A trace
  // with MANY wedges (a wind rose, an angular histogram) keeps theta/r,
  // because there each wedge's angle and radius are the data. Explicit
  // `labels=` overrides still win via the customized path below.
  _isNamedSingleWedge(row) {
    return this._namedWedge(row) !== null;
  },

  // A pie slice or a gauge band is ONE named wedge whose datum is its angular
  // width. Returns that trace when the hovered row is such a wedge.
  _namedWedge(row) {
    if (this.spec?.coords !== "polar") return null;
    const traces = Array.isArray(this.spec.traces) ? this.spec.traces : [];
    const trace = traces.find((t) => t && t.id === row.trace);
    if (!trace || typeof trace.name !== "string" || !trace.name.trim()) return null;
    const wedge = trace.kind === "bar" || trace.kind === "column" || trace.bar !== undefined
      || (trace.x0 !== undefined && trace.y0 !== undefined);
    const count = trace.n_marks ?? trace.n_points;
    return wedge && count === 1 ? trace : null;
  },

  // A single wedge's share of the wedges actually drawn. The angular width IS
  // the datum, so the readout that means something is "how much of the whole"
  // — and the whole is the span the wedges cover between them, not the axis
  // range: a gauge's four bands sweep 240 degrees of a full-turn axis, and
  // their shares must add to 100% of the gauge, not 67% of a circle.
  _wedgeSharePercent(trace) {
    const traces = Array.isArray(this.spec.traces) ? this.spec.traces : [];
    let total = 0;
    let own = 0;
    for (const t of traces) {
      const width = Number(t?.bar?.width);
      if (!Number.isFinite(width) || width <= 0) continue;
      const marks = t.n_marks ?? t.n_points;
      if (marks !== 1) return null; // a multi-wedge trace makes "share" undefined
      total += width;
      if (t.id === trace.id) own = width;
    }
    if (!(total > 0) || !(own > 0)) return null;
    return (own / total) * 100;
  },

  _defaultTooltipItems(row, labels = {}, aliases = {}) {
    const items = [];
    if (row.source !== undefined && row.target !== undefined) {
      items.push({ kind: "title", value: `${String(row.source)} → ${String(row.target)}` });
      if (row.value !== undefined) {
        items.push({
          kind: "field",
          label: typeof (labels as any).value === "string" ? (labels as any).value : "Flow",
          value: fmtValue(row.value, row.value_kind),
        });
      }
      return items;
    }
    if (row.node !== undefined) {
      items.push({ kind: "title", value: String(row.node) });
      if (row.value !== undefined) {
        items.push({
          kind: "field",
          label: typeof (labels as any).value === "string" ? (labels as any).value : "Total flow",
          value: fmtValue(row.value, row.value_kind),
        });
      }
      return items;
    }
    const rowTrace = (Array.isArray(this.spec.traces) ? this.spec.traces : [])
      .find((t) => t && t.id === row.trace);
    if (rowTrace && rowTrace.kind === "funnel" && row.stage !== undefined) {
      // A funnel stage's identity is its name and its conversion arithmetic;
      // the geometry slots are layout. The kernel ships a preformatted `*_text`
      // beside each number — it owns `value_format`/`percent_format`, and an
      // em dash where a ratio's denominator was zero — so the tooltip prints
      // those and never invents a format of its own.
      const field = (label, text, numeric) => {
        if (typeof text === "string") {
          // The em dash IS the readout for an undefined ratio (a stage after
          // a zero): dropping the row made the tooltip shape change between
          // stages, which reads as missing data rather than "no meaningful
          // number here".
          items.push({ kind: "field", label, value: text });
          return;
        }
        if (numeric !== undefined && numeric !== null && Number.isFinite(Number(numeric))) {
          items.push({ kind: "field", label, value: fmtValue(numeric) });
        }
      };
      items.push({ kind: "title", value: String(row.stage) });
      field(
        typeof (labels as any).value === "string" ? (labels as any).value : "Value",
        row.value_text,
        row.value,
      );
      // The prior value makes "From previous" checkable rather than asserted;
      // stage 0 has no prior and simply omits the row.
      if (row.prior_text || (row.prior !== undefined && row.prior !== null)) {
        field("From", row.prior_text, row.prior);
      }
      field("Overall", row.share_text, row.share);
      field("From previous", row.conversion_text, row.conversion);
      field("Drop-off", row.dropoff_text, row.dropoff);
      return items;
    }
    const seriesName = this._tooltipSeriesName(row);
    if (seriesName) items.push({ kind: "title", value: seriesName });
    const wedge = this._namedWedge(row);
    if (seriesName && wedge) {
      // The wedge's share is the only number that means anything here: theta
      // is where layout put it and the radius is the ring thickness. Skipped
      // when the name already carries a percentage (pie_chart bakes one in),
      // so a slice never reads "40% ... 40%".
      const share = /\d\s*%/.test(seriesName) ? null : this._wedgeSharePercent(wedge);
      if (share !== null) {
        items.push({ kind: "field", label: "share", value: `${share.toFixed(1)}%` });
      }
      return items;
    }
    if (row.x !== undefined) {
      const polar = this._polarTooltipField("x", row.x, row.x_kind);
      const { label, customized } = this._defaultTooltipLabel("x", "x", labels, aliases);
      // A numeric polar angle only appears when the user asked for the row
      // by naming it (`labels={"x": ...}`); authored spoke labels always show.
      if (!polar || !polar.omit || customized) {
        items.push({
          kind: "field",
          label: polar && !customized ? polar.label : label,
          value: polar ? polar.value : fmtValue(row.x, row.x_kind),
        });
      }
    }
    if (row.y !== undefined) {
      const polar = this._polarTooltipField("y", row.y, row.y_kind);
      const { label, customized } = this._defaultTooltipLabel("y", "y", labels, aliases);
      items.push({
        kind: "field",
        label: polar && !customized ? polar.label : label,
        value: fmtValue(row.y, row.y_kind),
      });
    }
    if (row.color_value !== undefined) {
      const { label } = this._defaultTooltipLabel(
        "color_value", "color", labels, aliases,
      );
      items.push({ kind: "field", label, value: fmtValue(row.color_value) });
    }
    if (row.color_category !== undefined) {
      const { label, customized } = this._defaultTooltipLabel(
        "color_category", "color", labels, aliases,
      );
      items.push(customized
        ? { kind: "field", label, value: String(row.color_category) }
        : { kind: "value", value: String(row.color_category) });
    }
    if (row.size_value !== undefined) {
      const { label } = this._defaultTooltipLabel(
        "size_value", "size", labels, aliases,
      );
      items.push({ kind: "field", label, value: fmtValue(row.size_value) });
    }
    if (!items.length) items.push({ kind: "value", value: `#${row.index}` });
    return items;
  },

  _tooltipLookup(row, field) {
    // "name" is a pseudo-field: the hovered trace's series name. Rows carry
    // only a trace id, but compositions whose category lives in the mark name
    // (a pie slice, a wind-rose band) need the tooltip template to reach it —
    // `xy.tooltip(title="{name}")` is how a pie shows category + value and
    // nothing else.
    if (field === "name") {
      const name = this._tooltipSeriesName(row);
      return name === null ? [undefined, undefined] : [name, undefined];
    }
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

  _tooltipItems(row) {
    const tooltip = this.spec.tooltip || {};
    const labels = tooltip.labels || {};
    const aliases = tooltip.aliases || {};
    if (!tooltip.title && !Array.isArray(tooltip.fields)) {
      return this._defaultTooltipItems(row, labels, aliases);
    }
    const formats = tooltip.format || {};
    const items = [];
    if (typeof tooltip.title === "string") {
      const title = tooltip.title.replace(/\{([^}]+)\}/g, (_, field) => {
        const [value, kind] = this._tooltipLookup(row, field);
        return value === undefined ? "" : this._formatTooltipValue(value, kind, formats[field]);
      });
      if (title) items.push({ kind: "title", value: title });
    }
    if (Array.isArray(tooltip.fields)) {
      for (const field of tooltip.fields) {
        if (typeof field !== "string") continue;
        const [value, kind] = this._tooltipLookup(row, field);
        if (value === undefined) continue;
        items.push({
          kind: "field",
          label: typeof labels[field] === "string" ? labels[field] : field,
          value: this._formatTooltipValue(value, kind, formats[field]),
        });
      }
    }
    return items.length ? items : this._defaultTooltipItems(row, labels, aliases);
  },

  _tooltipLines(items) {
    return items.map((item) => (
      item.kind === "field" ? `${item.label}: ${item.value}` : item.value
    ));
  },

  _renderBuiltinTooltip(items) {
    this.tooltip.textContent = "";
    for (const item of items) {
      const row = document.createElement("div");
      if (item.kind === "title") {
        this._applySlot(row, "tooltip_title");
        row.textContent = item.value;
      } else {
        this._applySlot(row, "tooltip_row");
        if (item.kind === "field") {
          const label = document.createElement("span");
          this._applySlot(label, "tooltip_label");
          label.textContent = item.label;
          row.appendChild(label);
        }
        const value = document.createElement("span");
        this._applySlot(value, "tooltip_value");
        value.textContent = item.value;
        row.appendChild(value);
      }
      this.tooltip.appendChild(row);
    }
  },

  // Anchor in data space so view changes carry the tooltip with its point.
  _setTooltipAnchor(hit, row, clientX, clientY) {
    const g = hit.g;
    if (!g) { this._tooltipAnchor = null; return; }
    const xAxis = g.xAxis || "x";
    const yAxis = g.yAxis || "y";
    let x = row.x;
    let y = row.y;
    if (g._cpuRibbon || g._cpuFunnel || !Number.isFinite(x) || !Number.isFinite(y)) {
      // Sankey rows describe a whole ribbon/node — and a funnel row a whole
      // stage segment — rather than a single data point, so their anchor
      // always follows the pick. Category rows also carry labels instead of
      // numeric coordinates and use the same fallback.
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
    const [lx, ly] = this._projectDataPoint(a.xAxis, a.yAxis, a.x, a.y);
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
    const items = this._tooltipItems(row);
    const lines = this._tooltipLines(items);
    if (!this._customTooltip) {
      // textContent/text nodes, not innerHTML: field labels and category
      // values are user data and must never be parsed as markup.
      this._renderBuiltinTooltip(items);
    }
    if (this.a11yLive && options.announce !== false) {
      const prefix = this._a11yKeyboardReadout;
      const detail = lines.join(", ");
      // A funnel is an ordered process, and its keyboard walk should say so:
      // "Stage 2 of 5", not "Point 2 of 5".
      const g = this._hoverTarget && this._hoverTarget.g;
      const noun = g && g.trace && g.trace.kind === "funnel" ? "Stage" : "Point";
      const announcement = prefix
        ? `${noun} ${prefix.flat + 1} of ${prefix.total}. ${detail}`
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
