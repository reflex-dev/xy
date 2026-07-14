// ChartView annotation layer (§ chrome): reference lines/zones already draw
// in _drawChrome; this part owns the 2D-canvas overlay — markers, arrows,
// shape fills, and collision-nudged labels. Split out of 50_chartview.js;
// augments the prototype so `this.*` is unchanged.

Object.assign(ChartView.prototype, {
  _annotationPaint(style, fallback) {
    return safeCssPaint(this.root, style && style.color, fallback);
  },

  _annotationLabelPaint(style, fallback) {
    return safeCssPaint(this.root, style && (style.label_color || style.color), fallback);
  },

  _annotationStrokePaint(style, fallback) {
    return safeCssPaint(this.root, style && style.stroke_color, fallback);
  },

  _drawAnnotationMarker(ctx, x, y, style, ann) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    const r = Math.max(1, this._styleNumber(style, "size", Number(ann.size) || 8) / 2);
    const symbol = ["circle", "square", "diamond", "cross"].includes(ann.symbol) ? ann.symbol : "circle";
    ctx.save();
    ctx.globalAlpha = this._styleNumber(style, "opacity", 1);
    ctx.fillStyle = this._annotationPaint(style, [0.15, 0.39, 0.92, 1]);
    ctx.strokeStyle = symbol === "cross"
      ? this._annotationPaint(style, [0.15, 0.39, 0.92, 1])
      : this._annotationStrokePaint(style, [1, 1, 1, 1]);
    ctx.lineWidth = Math.max(0, this._styleNumber(style, "stroke_width", 1.5));
    ctx.beginPath();
    if (symbol === "square") {
      ctx.rect(x - r, y - r, r * 2, r * 2);
    } else if (symbol === "diamond") {
      ctx.moveTo(x, y - r);
      ctx.lineTo(x + r, y);
      ctx.lineTo(x, y + r);
      ctx.lineTo(x - r, y);
      ctx.closePath();
    } else if (symbol === "cross") {
      ctx.moveTo(x - r, y);
      ctx.lineTo(x + r, y);
      ctx.moveTo(x, y - r);
      ctx.lineTo(x, y + r);
      ctx.stroke();
      ctx.restore();
      return;
    } else {
      ctx.arc(x, y, r, 0, Math.PI * 2);
    }
    ctx.fill();
    if (ctx.lineWidth > 0) ctx.stroke();
    ctx.restore();
  },

  _drawArrowLine(ctx, x0, y0, x1, y1, style) {
    if (![x0, y0, x1, y1].every(Number.isFinite)) return;
    const angle = Math.atan2(y1 - y0, x1 - x0);
    const head = Math.max(7, this._styleNumber(style, "head_size", 8));
    ctx.save();
    ctx.globalAlpha = this._styleNumber(style, "opacity", 1);
    ctx.strokeStyle = this._annotationPaint(style, [0.4, 0.44, 0.52, 1]);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.lineWidth = Math.max(0.5, this._styleNumber(style, "width", 1.5));
    ctx.setLineDash(Array.isArray(style.dash) ? style.dash :
      (typeof style.dash === "string" ? style.dash.split(",").map(Number) : []));
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(
      x1 - head * Math.cos(angle - Math.PI / 6),
      y1 - head * Math.sin(angle - Math.PI / 6)
    );
    ctx.lineTo(
      x1 - head * Math.cos(angle + Math.PI / 6),
      y1 - head * Math.sin(angle + Math.PI / 6)
    );
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  },

  _drawAnnotationShapes(ctx) {
    const annotations = Array.isArray(this.spec.annotations) ? this.spec.annotations : [];
    if (!annotations.length) return;
    const p = this.plot;
    ctx.save();
    ctx.beginPath();
    ctx.rect(p.x, p.y, p.w, p.h);
    ctx.clip();
    for (const ann of annotations) {
      const style = ann && typeof ann.style === "object" ? ann.style : {};
      if (ann.kind === "band") {
        const vertical = ann.axis === "x";
        const a = vertical ? this._dataPxX(Number(ann.start)) : this._dataPxY(Number(ann.start));
        const b = vertical ? this._dataPxX(Number(ann.end)) : this._dataPxY(Number(ann.end));
        if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
        const lo = Math.max(vertical ? p.x : p.y, Math.min(a, b));
        const hi = Math.min(vertical ? p.x + p.w : p.y + p.h, Math.max(a, b));
        if (hi <= lo) continue;
        ctx.save();
        ctx.globalAlpha = this._styleNumber(style, "opacity", 0.14);
        ctx.fillStyle = this._annotationPaint(style, [0.39, 0.45, 0.55, 1]);
        const start = Math.max(0, Math.min(1, Number(style.span_start) || 0));
        const rawEnd = style.span_end === undefined ? 1 : Number(style.span_end);
        const end = Math.max(start, Math.min(1, Number.isFinite(rawEnd) ? rawEnd : 1));
        if (vertical) ctx.fillRect(lo, p.y + (1 - end) * p.h, hi - lo, (end - start) * p.h);
        else ctx.fillRect(p.x + start * p.w, lo, (end - start) * p.w, hi - lo);
        ctx.restore();
      } else if (ann.kind === "rule") {
        const vertical = ann.axis === "x";
        const pos = vertical ? this._dataPxX(Number(ann.value)) : this._dataPxY(Number(ann.value));
        if (!Number.isFinite(pos)) continue;
        if (vertical && (pos < p.x - 1 || pos > p.x + p.w + 1)) continue;
        if (!vertical && (pos < p.y - 1 || pos > p.y + p.h + 1)) continue;
        const crisp = Math.round(pos) + 0.5;
        ctx.save();
        ctx.globalAlpha = this._styleNumber(style, "opacity", 1);
        ctx.strokeStyle = this._annotationPaint(style, [0.4, 0.44, 0.52, 1]);
        ctx.lineWidth = Math.max(0.5, this._styleNumber(style, "width", 1.5));
        ctx.setLineDash(Array.isArray(style.dash) ? style.dash :
          (typeof style.dash === "string" ? style.dash.split(",").map(Number) : []));
        ctx.beginPath();
        const start = Math.max(0, Math.min(1, Number(style.span_start) || 0));
        const rawEnd = style.span_end === undefined ? 1 : Number(style.span_end);
        const end = Math.max(start, Math.min(1, Number.isFinite(rawEnd) ? rawEnd : 1));
        if (vertical) {
          ctx.moveTo(crisp, p.y + (1 - end) * p.h);
          ctx.lineTo(crisp, p.y + (1 - start) * p.h);
        } else {
          ctx.moveTo(p.x + start * p.w, crisp);
          ctx.lineTo(p.x + end * p.w, crisp);
        }
        ctx.stroke();
        ctx.restore();
      } else if (ann.kind === "arrow") {
        this._drawArrowLine(
          ctx,
          this._dataPxX(Number(ann.x0)),
          this._dataPxY(Number(ann.y0)),
          this._dataPxX(Number(ann.x1)),
          this._dataPxY(Number(ann.y1)),
          style
        );
      } else if (ann.kind === "callout") {
        const px = this._dataPxX(Number(ann.x));
        const py = this._dataPxY(Number(ann.y));
        const dx = Number.isFinite(Number(ann.dx)) ? Number(ann.dx) : 0;
        const dy = Number.isFinite(Number(ann.dy)) ? Number(ann.dy) : 0;
        this._drawArrowLine(ctx, px + dx, py + dy, px, py, style);
      } else if (ann.kind === "marker") {
        this._drawAnnotationMarker(
          ctx,
          this._dataPxX(Number(ann.x)),
          this._dataPxY(Number(ann.y)),
          style,
          ann
        );
      }
    }
    ctx.restore();
  },

  _drawAnnotationLabels(updateLabels) {
    if (!updateLabels) return;
    const annotations = Array.isArray(this.spec.annotations) ? this.spec.annotations : [];
    if (!annotations.length) return;
    const p = this.plot;
    for (const ann of annotations) {
      const text = typeof ann.text === "string" ? ann.text : "";
      if (!text) continue;
      const style = ann && typeof ann.style === "object" ? ann.style : {};
      let px = null;
      let py = null;
      if (ann.kind === "text") {
        if (style.coordinate_space === "axes_fraction") {
          px = p.x + Number(ann.x) * p.w;
          py = p.y + (1 - Number(ann.y)) * p.h;
        } else if (style.coordinate_space === "figure_fraction") {
          px = Number(ann.x) * this.size.w;
          py = (1 - Number(ann.y)) * this.size.h;
        } else if (style.coordinate_space === "yaxis_transform") {
          px = p.x + Number(ann.x) * p.w;
          py = this._dataPxY(Number(ann.y));
        } else if (style.coordinate_space === "xaxis_transform") {
          px = this._dataPxX(Number(ann.x));
          py = p.y + (1 - Number(ann.y)) * p.h;
        } else {
          px = this._dataPxX(Number(ann.x));
          py = this._dataPxY(Number(ann.y));
        }
      } else if (ann.kind === "rule") {
        if (ann.axis === "x") {
          px = this._dataPxX(Number(ann.value));
          py = p.y + 6;
        } else {
          px = p.x + p.w - 6;
          py = this._dataPxY(Number(ann.value));
        }
      } else if (ann.kind === "band") {
        if (ann.axis === "x") {
          px = (this._dataPxX(Number(ann.start)) + this._dataPxX(Number(ann.end))) / 2;
          py = p.y + 6;
        } else {
          px = p.x + p.w - 6;
          py = (this._dataPxY(Number(ann.start)) + this._dataPxY(Number(ann.end))) / 2;
        }
      } else if (ann.kind === "arrow") {
        px = (this._dataPxX(Number(ann.x0)) + this._dataPxX(Number(ann.x1))) / 2;
        py = (this._dataPxY(Number(ann.y0)) + this._dataPxY(Number(ann.y1))) / 2;
      } else if (ann.kind === "callout") {
        px = this._dataPxX(Number(ann.x));
        py = this._dataPxY(Number(ann.y));
      } else if (ann.kind === "marker") {
        px = this._dataPxX(Number(ann.x));
        py = this._dataPxY(Number(ann.y));
      }
      if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
      if (px < p.x - 24 || px > p.x + p.w + 24 || py < p.y - 24 || py > p.y + p.h + 24) {
        continue;
      }
      const d = document.createElement("div");
      d.textContent = text;
      const dx = Number.isFinite(Number(ann.dx)) ? Number(ann.dx) : 0;
      const dy = Number.isFinite(Number(ann.dy)) ? Number(ann.dy) : 0;
      const anchor = ann.anchor === "middle" ? "-50%" : ann.anchor === "end" ? "-100%" : "0";
      // Structural inline only (position telegraphs the anchor); font + default
      // color live in the defeatable :where() stylesheet so utility classes win.
      d.style.cssText =
        `position:absolute;left:${px + dx}px;top:${py + dy}px;` +
        `transform:translate(${anchor},0);pointer-events:none;` +
        `white-space:pre-line;text-align:center;`;
      this._applySlot(d, "annotation_label");
      this._applyClass(d, ann.class_name);
      this._applyStyle(d, style);
      // Only pin color inline when the annotation asked for one — otherwise the
      // stylesheet's --chart-annotation-text default stays overridable by CSS.
      if (style && (style.label_color || style.color)) {
        d.style.color = this._annotationLabelPaint(style, this.theme.label);
      }
      this.labels.appendChild(d);
    }
  },
});
