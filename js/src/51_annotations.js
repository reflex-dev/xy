// ChartView annotation layer (§ chrome): reference lines/zones already draw
// in _drawChrome; this part owns the 2D-canvas overlay — markers, arrows,
// shape fills, and collision-nudged labels. Split out of 50_chartview.js;
// augments the prototype so `this.*` is unchanged.

// Annotation style keys consumed by the canvas shape (shaft/head/marker
// geometry and paint) — never forwarded to the DOM label as CSS.
const FC_ANNOTATION_SHAPE_STYLE_KEYS = new Set([
  "color",
  "label_color",
  "width",
  "head_size",
  "head_style",
  "tail_style",
  "shaft_width_start",
  "shaft_width_end",
  "curve",
  "angle_a",
  "angle_b",
  "gap_start",
  "gap_end",
  "start_offset",
  "label_clear",
  "dash",
  "span_start",
  "span_end",
  "size",
  "symbol",
  "stroke_color",
  "stroke_width",
  "coordinate_space",
]);

// Arrow path geometry shared by every arrow/callout draw (mirrored by the
// static exporters in python/xy/_arrowgeom.py — keep the two in sync):
// an optional quadratic control point from `curve` (matplotlib arc3 rad,
// bulge as a fraction of chord length) or `angle_a`/`angle_b` (matplotlib
// angle3/angle departure/arrival angles in degrees, y-up screen space —
// control point at the ray intersection), then `gap_start`/`gap_end` px
// trims along the path tangents (label/point clearance). `start_offset`
// ("x,y" px) shifts the start point — matplotlib's relpos: the arrow leaves
// the label's box CENTER, not its anchor. `label_clear`
// ("left,right,up,down" px, y-down) is the start label's extents rectangle
// around the shifted start: the start trims to where the departure tangent
// exits it — matplotlib's text-patch clipping.
function fcLabelClearExit(style, tangent) {
  if (typeof style.label_clear !== "string") return 0;
  const parts = style.label_clear.split(",").map(Number);
  if (parts.length !== 4 || parts.some((p) => !Number.isFinite(p) || p < 0)) return 0;
  const [left, right, up, down] = parts;
  const [tx, ty] = tangent;
  const exitX = tx > 1e-9 ? right / tx : tx < -1e-9 ? left / -tx : Infinity;
  const exitY = ty > 1e-9 ? down / ty : ty < -1e-9 ? up / -ty : Infinity;
  const exit = Math.min(exitX, exitY);
  return Number.isFinite(exit) ? exit : 0;
}

function fcArrowGeometry(x0, y0, x1, y1, style) {
  const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : null);
  if (typeof style.start_offset === "string") {
    const offset = style.start_offset.split(",").map(Number);
    if (offset.length === 2 && offset.every(Number.isFinite)) {
      x0 += offset[0];
      y0 += offset[1];
    }
  }
  const angleA = num(style.angle_a);
  const angleB = num(style.angle_b);
  const curve = num(style.curve);
  let cx = null;
  let cy = null;
  if (angleA !== null && angleB !== null) {
    const a = (-angleA * Math.PI) / 180; // spec angles are y-up; canvas is y-down
    const b = (-angleB * Math.PI) / 180;
    const denom = Math.cos(a) * Math.sin(b) - Math.sin(a) * Math.cos(b);
    if (Math.abs(denom) > 1e-6) {
      const t = ((x1 - x0) * Math.sin(b) - (y1 - y0) * Math.cos(b)) / denom;
      cx = x0 + t * Math.cos(a);
      cy = y0 + t * Math.sin(a);
    }
  } else if (curve) {
    const dx = x1 - x0;
    const dy = y1 - y0;
    // arc3 rad > 0 bulges to the chord's left in matplotlib's y-up plane.
    cx = (x0 + x1) / 2 + curve * dy;
    cy = (y0 + y1) / 2 - curve * dx;
  }
  const toward = (px, py, qx, qy) => {
    const d = Math.hypot(qx - px, qy - py) || 1;
    return [(qx - px) / d, (qy - py) / d];
  };
  const t0 = cx === null ? toward(x0, y0, x1, y1) : toward(x0, y0, cx, cy);
  const t1 = cx === null ? toward(x1, y1, x0, y0) : toward(x1, y1, cx, cy);
  const gapStart = Math.max(0, num(style.gap_start) || 0, fcLabelClearExit(style, t0));
  const gapEnd = Math.max(0, num(style.gap_end) || 0);
  const span = Math.hypot(x1 - x0, y1 - y0);
  const trim = gapStart + gapEnd < span * 0.9;
  const p0 = trim ? [x0 + gapStart * t0[0], y0 + gapStart * t0[1]] : [x0, y0];
  const p1 = trim ? [x1 + gapEnd * t1[0], y1 + gapEnd * t1[1]] : [x1, y1];
  // Tangent INTO each endpoint (head/tail orientation).
  const dir1 = cx === null ? toward(p0[0], p0[1], p1[0], p1[1]) : toward(cx, cy, p1[0], p1[1]);
  const dir0 = cx === null ? toward(p1[0], p1[1], p0[0], p0[1]) : toward(cx, cy, p0[0], p0[1]);
  return { p0, p1, control: cx === null ? null : [cx, cy], dir0, dir1 };
}

// The shaft as a point list (quadratic Bézier sampled when curved).
function fcArrowShaftPoints(geom, samples = 24) {
  const [x0, y0] = geom.p0;
  const [x1, y1] = geom.p1;
  if (!geom.control) return [[x0, y0], [x1, y1]];
  const [cx, cy] = geom.control;
  const points = [];
  for (let i = 0; i <= samples; i++) {
    const t = i / samples;
    const u = 1 - t;
    points.push([u * u * x0 + 2 * u * t * cx + t * t * x1, u * u * y0 + 2 * u * t * cy + t * t * y1]);
  }
  return points;
}

// The polyline with `trim` px of arclength removed from its end (a tapered
// shaft ends at the head BASE — a full-length shaft would swallow the head).
function fcTrimPolylineEnd(points, trim) {
  if (!(trim > 0) || points.length < 2) return points;
  const out = points.slice();
  let remaining = trim;
  while (out.length >= 2) {
    const [ax, ay] = out[out.length - 2];
    const [bx, by] = out[out.length - 1];
    const seg = Math.hypot(bx - ax, by - ay);
    if (seg > remaining) {
      const t = 1 - remaining / seg;
      out[out.length - 1] = [ax + t * (bx - ax), ay + t * (by - ay)];
      return out;
    }
    remaining -= seg;
    out.pop();
  }
  return out;
}

// The shaft as a filled polygon whose width interpolates from w0 to w1
// (matplotlib's fancy/simple/wedge arrowstyles are filled tapered shafts).
function fcTaperPolygon(points, w0, w1) {
  const left = [];
  const right = [];
  const count = points.length;
  for (let i = 0; i < count; i++) {
    const [px, py] = points[i];
    const [ax, ay] = points[Math.max(0, i - 1)];
    const [bx, by] = points[Math.min(count - 1, i + 1)];
    const d = Math.hypot(bx - ax, by - ay) || 1;
    const nx = -(by - ay) / d;
    const ny = (bx - ax) / d;
    const half = (w0 + (w1 - w0) * (i / Math.max(1, count - 1))) / 2;
    left.push([px + half * nx, py + half * ny]);
    right.push([px - half * nx, py - half * ny]);
  }
  return left.concat(right.reverse());
}

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
    const geom = fcArrowGeometry(x0, y0, x1, y1, style);
    ctx.save();
    ctx.globalAlpha = this._styleNumber(style, "opacity", 1);
    ctx.strokeStyle = this._annotationPaint(style, [0.4, 0.44, 0.52, 1]);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.lineWidth = Math.max(0.5, this._styleNumber(style, "width", 1.5));
    ctx.setLineDash(Array.isArray(style.dash) ? style.dash :
      (typeof style.dash === "string" ? style.dash.split(",").map(Number) : []));
    const w0 = Number(style.shaft_width_start);
    const w1 = Number(style.shaft_width_end);
    const headStyle = style.head_style || "triangle";
    const head = Math.max(4, this._styleNumber(style, "head_size", 8));
    if (Number.isFinite(w0) || Number.isFinite(w1)) {
      let points = fcArrowShaftPoints(geom);
      if (headStyle === "triangle") {
        points = fcTrimPolylineEnd(points, head * Math.cos(Math.PI / 6));
      }
      const polygon = fcTaperPolygon(
        points,
        Number.isFinite(w0) ? w0 : 1,
        Number.isFinite(w1) ? w1 : 1
      );
      ctx.beginPath();
      ctx.moveTo(polygon[0][0], polygon[0][1]);
      for (let i = 1; i < polygon.length; i++) ctx.lineTo(polygon[i][0], polygon[i][1]);
      ctx.closePath();
      ctx.fill();
    } else {
      ctx.beginPath();
      ctx.moveTo(geom.p0[0], geom.p0[1]);
      if (geom.control) ctx.quadraticCurveTo(geom.control[0], geom.control[1], geom.p1[0], geom.p1[1]);
      else ctx.lineTo(geom.p1[0], geom.p1[1]);
      ctx.stroke();
    }
    this._drawArrowEnd(ctx, geom.p1, geom.dir1, headStyle, head);
    this._drawArrowEnd(ctx, geom.p0, geom.dir0, style.tail_style || "none", head);
    ctx.restore();
  },

  // One arrow endpoint decoration. dir is the unit tangent INTO the point;
  // styles mirror matplotlib arrowstyles: "triangle" (filled, "-|>"/fancy),
  // "v" (open stroke, "->"), "bar" ("|-|" caps), "none".
  _drawArrowEnd(ctx, point, dir, endStyle, head) {
    if (endStyle === "none") return;
    const [px, py] = point;
    const angle = Math.atan2(dir[1], dir[0]);
    ctx.beginPath();
    if (endStyle === "bar") {
      ctx.moveTo(px - (head / 2) * Math.sin(angle), py + (head / 2) * Math.cos(angle));
      ctx.lineTo(px + (head / 2) * Math.sin(angle), py - (head / 2) * Math.cos(angle));
      ctx.stroke();
      return;
    }
    const wing = (side) => [
      px - head * Math.cos(angle - side * Math.PI / 6),
      py - head * Math.sin(angle - side * Math.PI / 6),
    ];
    const [ax, ay] = wing(1);
    const [bx, by] = wing(-1);
    if (endStyle === "v") {
      ctx.moveTo(ax, ay);
      ctx.lineTo(px, py);
      ctx.lineTo(bx, by);
      ctx.stroke();
      return;
    }
    ctx.moveTo(px, py);
    ctx.lineTo(ax, ay);
    ctx.lineTo(bx, by);
    ctx.closePath();
    ctx.fill();
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
      const anchor = ann.anchor === "middle" ? "-50%" : ann.anchor === "end" ? "-100%" : "0px";
      // matplotlib's va, matching the SVG/raster exporters: the default is
      // the text BASELINE at the anchor (~0.35em of descent hangs below it),
      // not the box top.
      const va = style.vertical_align;
      const vAnchor =
        va === "center" || va === "middle" ? "-50%"
          : va === "bottom" ? "-100%"
          : va === "top" ? "0px"
          : "calc(-100% + 0.35em)";
      // Structural inline only (position telegraphs the anchor); font + default
      // color live in the defeatable :where() stylesheet so utility classes win.
      // width:max-content: shrink-to-fit for an absolutely positioned label is
      // capped by the distance to the containing block's edge, so an end/middle
      // anchored label near the right edge would wrap word-per-word BEFORE the
      // translate(-100%) shift moves it back inside.
      d.style.cssText =
        `position:absolute;left:${px + dx}px;top:${py + dy}px;` +
        `transform:translate(${anchor},${vAnchor});pointer-events:none;` +
        `white-space:pre-line;text-align:center;width:max-content;`;
      this._applySlot(d, "annotation_label");
      this._applyClass(d, ann.class_name);
      // Shape-geometry/paint keys style the canvas shape, not the label DOM —
      // e.g. an arrow's shaft `width` must not become CSS width on the label.
      const labelStyle = {};
      for (const [key, value] of Object.entries(style)) {
        if (FC_ANNOTATION_SHAPE_STYLE_KEYS.has(key)) continue;
        labelStyle[key] = value;
      }
      this._applyStyle(d, labelStyle);
      // Only pin color inline when the annotation asked for one — otherwise the
      // stylesheet's --chart-annotation-text default stays overridable by CSS.
      if (style && (style.label_color || style.color)) {
        d.style.color = this._annotationLabelPaint(style, this.theme.label);
      }
      this.labels.appendChild(d);
      // matplotlib anchors the TEXT at its position; a bbox patch grows
      // outward around it. A padded/bordered label must therefore anchor by
      // its text edge, not its box edge — shift the translate by the leading
      // padding+border on each anchored side (a no-op for plain labels).
      const cs = getComputedStyle(d);
      const edge = (pad, border) => (parseFloat(pad) || 0) + (parseFloat(border) || 0);
      const padL = edge(cs.paddingLeft, cs.borderLeftWidth);
      const padR = edge(cs.paddingRight, cs.borderRightWidth);
      const padT = edge(cs.paddingTop, cs.borderTopWidth);
      const padB = edge(cs.paddingBottom, cs.borderBottomWidth);
      if (padL || padR || padT || padB) {
        const hShift = anchor === "-100%" ? padR : anchor === "-50%" ? 0 : -padL;
        // Bottom-referenced anchors (bottom, and the baseline default) ride
        // up as bottom padding grows; top-referenced ones ride down.
        const vShift =
          vAnchor === "-50%" ? 0 : vAnchor === "0px" ? -padT : padB;
        d.style.transform =
          `translate(calc(${anchor} + ${hShift}px), calc(${vAnchor} + ${vShift}px))`;
      }
    }
  },
});
