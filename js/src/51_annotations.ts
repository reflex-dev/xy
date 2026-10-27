import { buildLutData } from "./10_colormaps";
import { parseColor, safeCssPaint } from "./20_theme";
import { ChartView } from "./50_chartview";

// ChartView annotation layer (§ chrome): reference lines/zones already draw
// in _drawChrome; this part owns the 2D-canvas overlay — markers, arrows,
// shape fills, and collision-nudged labels. Split out of 50_chartview.js;
// augments the prototype so `this.*` is unchanged.

// Annotation style keys consumed by the canvas shape (shaft/head/marker
// geometry and paint) — never forwarded to the DOM label as CSS.
const XY_ANNOTATION_SHAPE_STYLE_KEYS = new Set([
  "color",
  "label_color",
  "label_opacity",
  "opacity",
  "width",
  "head_size",
  "head_style",
  "tail_style",
  "shaft_width_start",
  "shaft_width_end",
  "curve",
  "angle_a",
  "angle_b",
  "elbow",
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
function xyLabelClearExit(style, tangent) {
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

function xyArrowGeometry(x0, y0, x1, y1, style) {
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
  const gapStart = Math.max(0, num(style.gap_start) || 0, xyLabelClearExit(style, t0));
  const gapEnd = Math.max(0, num(style.gap_end) || 0);
  const span = Math.hypot(x1 - x0, y1 - y0);
  const trim = gapStart + gapEnd < span * 0.9;
  const p0 = trim ? [x0 + gapStart * t0[0], y0 + gapStart * t0[1]] : [x0, y0];
  const p1 = trim ? [x1 + gapEnd * t1[0], y1 + gapEnd * t1[1]] : [x1, y1];
  // Tangent INTO each endpoint (head/tail orientation).
  const dir1 = cx === null ? toward(p0[0], p0[1], p1[0], p1[1]) : toward(cx, cy, p1[0], p1[1]);
  const dir0 = cx === null ? toward(p1[0], p1[1], p0[0], p0[1]) : toward(cx, cy, p0[0], p0[1]);
  return {
    p0,
    p1,
    control: cx === null ? null : [cx, cy],
    elbow: Boolean(style.elbow),
    dir0,
    dir1,
  };
}

// The shaft as a point list (quadratic Bézier sampled when curved).
function xyArrowShaftPoints(geom, samples = 24) {
  const [x0, y0] = geom.p0;
  const [x1, y1] = geom.p1;
  if (!geom.control) return [[x0, y0], [x1, y1]];
  const [cx, cy] = geom.control;
  if (geom.elbow) return [[x0, y0], [cx, cy], [x1, y1]];
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
function xyTrimPolylineEnd(points, trim) {
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

function xyCanvasRegularPolygon(ctx, cx, cy, radius, points, start = -Math.PI / 2) {
  for (let index = 0; index < points; index++) {
    const angle = start + index * 2 * Math.PI / points;
    const x = cx + radius * Math.cos(angle);
    const y = cy + radius * Math.sin(angle);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
}

// Canvas counterpart of POINT_FS/_SYMBOL_BUILDERS. Returns true for the two
// line-only symbols, whose authored paint is a stroke rather than a fill.
function xyCanvasScatterSymbol(ctx, symbol, cx, cy, diameter) {
  const radius = diameter / 2;
  ctx.beginPath();
  if (symbol === 0 || symbol === 12) {
    ctx.arc(cx, cy, radius, 0, 2 * Math.PI);
  } else if (symbol === 1 || symbol === 13) {
    ctx.rect(cx - radius, cy - radius, diameter, diameter);
  } else if (symbol === 2 || symbol === 14) {
    const yr = Math.SQRT2 * radius;
    const xr = symbol === 14 ? 0.6 * yr : yr;
    ctx.moveTo(cx, cy - yr);
    ctx.lineTo(cx + xr, cy);
    ctx.lineTo(cx, cy + yr);
    ctx.lineTo(cx - xr, cy);
    ctx.closePath();
  } else if (symbol === 3) {
    ctx.moveTo(cx, cy - radius);
    ctx.lineTo(cx + radius, cy + radius);
    ctx.lineTo(cx - radius, cy + radius);
    ctx.closePath();
  } else if (symbol === 8) {
    ctx.moveTo(cx, cy + radius);
    ctx.lineTo(cx + radius, cy - radius);
    ctx.lineTo(cx - radius, cy - radius);
    ctx.closePath();
  } else if (symbol === 9) {
    ctx.moveTo(cx - radius, cy);
    ctx.lineTo(cx + radius, cy - radius);
    ctx.lineTo(cx + radius, cy + radius);
    ctx.closePath();
  } else if (symbol === 10) {
    ctx.moveTo(cx + radius, cy);
    ctx.lineTo(cx - radius, cy - radius);
    ctx.lineTo(cx - radius, cy + radius);
    ctx.closePath();
  } else if (symbol === 4) {
    const inner = 0.34 * radius;
    ctx.moveTo(cx - inner, cy - radius);
    ctx.lineTo(cx + inner, cy - radius);
    ctx.lineTo(cx + inner, cy - inner);
    ctx.lineTo(cx + radius, cy - inner);
    ctx.lineTo(cx + radius, cy + inner);
    ctx.lineTo(cx + inner, cy + inner);
    ctx.lineTo(cx + inner, cy + radius);
    ctx.lineTo(cx - inner, cy + radius);
    ctx.lineTo(cx - inner, cy + inner);
    ctx.lineTo(cx - radius, cy + inner);
    ctx.lineTo(cx - radius, cy - inner);
    ctx.lineTo(cx - inner, cy - inner);
    ctx.closePath();
  } else if (symbol === 11) {
    const wide = 0.72 * radius;
    const narrow = 0.28 * radius;
    ctx.moveTo(cx - wide, cy - radius);
    ctx.lineTo(cx, cy - narrow);
    ctx.lineTo(cx + wide, cy - radius);
    ctx.lineTo(cx + radius, cy - wide);
    ctx.lineTo(cx + narrow, cy);
    ctx.lineTo(cx + radius, cy + wide);
    ctx.lineTo(cx + wide, cy + radius);
    ctx.lineTo(cx, cy + narrow);
    ctx.lineTo(cx - wide, cy + radius);
    ctx.lineTo(cx - radius, cy + wide);
    ctx.lineTo(cx - narrow, cy);
    ctx.lineTo(cx - radius, cy - wide);
    ctx.closePath();
  } else if (symbol === 15) {
    ctx.moveTo(cx - radius, cy);
    ctx.lineTo(cx + radius, cy);
    ctx.moveTo(cx, cy - radius);
    ctx.lineTo(cx, cy + radius);
    return true;
  } else if (symbol === 16) {
    const edge = Math.SQRT1_2 * radius;
    ctx.moveTo(cx - edge, cy - edge);
    ctx.lineTo(cx + edge, cy + edge);
    ctx.moveTo(cx + edge, cy - edge);
    ctx.lineTo(cx - edge, cy + edge);
    return true;
  } else if (symbol === 5 || symbol === 6) {
    xyCanvasRegularPolygon(ctx, cx, cy, radius, symbol === 5 ? 6 : 5);
  } else if (symbol === 7) {
    for (let index = 0; index < 10; index++) {
      const r = index % 2 === 0 ? radius : radius * 0.45;
      const angle = -Math.PI / 2 + index * Math.PI / 5;
      const x = cx + r * Math.cos(angle);
      const y = cy + r * Math.sin(angle);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
  } else {
    ctx.arc(cx, cy, radius, 0, 2 * Math.PI);
  }
  return false;
}

// The shaft as a filled polygon whose width interpolates from w0 to w1
// (matplotlib's fancy/simple/wedge arrowstyles are filled tapered shafts).
function xyTaperPolygon(points, w0, w1) {
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

// Canvas-authored scatter glyphs and clipped annotation marks share the same
// annular-sector boundary as GL/SVG marks. A rectangular canvas clip lets a
// large marker bleed into the hole (or a chord cross a sector's missing
// wedge), so trace the visible outer arc and return along the inner arc.
function xyClipPolarCanvas(ctx, geom) {
  const denom = geom.rHi - geom.rOrigin;
  const visibleFraction = Math.abs(denom) > 1e-30
    ? geom.hole + (1 - geom.hole) * ((geom.rLo - geom.rOrigin) / denom)
    : geom.hole;
  const inner = Math.max(
    0,
    Math.min(geom.radius, visibleFraction * geom.radius),
  );
  const start = -geom.angleStart;
  const end = -geom.angleEnd;
  const anticlockwise = geom.dir > 0;
  ctx.beginPath();
  ctx.moveTo(
    geom.cx + geom.radius * Math.cos(start),
    geom.cy + geom.radius * Math.sin(start),
  );
  ctx.arc(geom.cx, geom.cy, geom.radius, start, end, anticlockwise);
  if (inner > 1e-6) {
    ctx.lineTo(
      geom.cx + inner * Math.cos(end),
      geom.cy + inner * Math.sin(end),
    );
    ctx.arc(geom.cx, geom.cy, inner, end, start, !anticlockwise);
  } else {
    ctx.lineTo(geom.cx, geom.cy);
  }
  ctx.closePath();
  ctx.clip();
}

Object.assign(ChartView.prototype, {
  _authoredScatterRgba(g, index, continuousLut = null, paletteRgba = null) {
    if (g.colorMode === 3 && g._cpu.rgba) {
      const offset = index * 4;
      return Array.from(g._cpu.rgba.slice(offset, offset + 4), (value: number) => value / 255);
    }
    if (g.colorMode === 2 && g._cpu.color && paletteRgba && paletteRgba.length) {
      return paletteRgba[Math.round(g._cpu.color[index]) % paletteRgba.length];
    }
    if (g.colorMode === 1 && g._cpu.color) {
      // The caller prepares this once per trace/redraw. Falling back to a
      // default color is preferable to rebuilding 256 stops for every point.
      if (!continuousLut) return g.color || [0.3, 0.47, 0.66, 1];
      const lut = continuousLut;
      const value = g._cpu.color[index];
      const unit = g._cpu.color instanceof Uint8Array ? value / 255 : value;
      const slot = Math.max(0, Math.min(255, Math.round(unit * 255))) * 4;
      return [lut[slot] / 255, lut[slot + 1] / 255, lut[slot + 2] / 255, 1];
    }
    return g.color || [0.3, 0.47, 0.66, 1];
  },

  _drawAuthoredScatterMarkers(ctx) {
    const draws = (this._authoredScatterDraws || []).filter(
      ({ g }) => g && g.trace?.kind === "scatter" && g.authoredMarker
    );
    if (!draws.length) return;
    const p = this.plot;
    const polarGeom = this._polarGeometry();
    ctx.save();
    ctx.beginPath();
    ctx.rect(p.x, p.y, p.w, p.h);
    ctx.clip();
    if (polarGeom) xyClipPolarCanvas(ctx, polarGeom);
    for (const { g, opacityScale } of draws) {
      if (!g._cpu) continue;
      const style = g.trace.style || {};
      const markerPath = style.marker_path;
      const markerGlyph = style.marker_glyph;
      const zoomStyle = this._pointZoomStyle(g);
      const colormap = g.trace.color?.colormap || "viridis";
      if (g.colorMode === 1 && g._authoredLutName !== colormap) {
        g._authoredLutName = colormap;
        g._authoredLut = buildLutData(colormap);
      }
      const continuousLut = g.colorMode === 1 ? g._authoredLut : null;
      const palette = g.trace.color?.palette || [];
      const paletteRgba = g.colorMode === 2 && palette.length
        ? palette.map((c) => parseColor(this.root, c, g.color))
        : null;
      for (let index = 0; index < g.n; index++) {
        const sourceIndex = g._visMap ? g._visMap[index] : index;
        const x = this._decodeValue(g._cpu.x, g.xMeta, sourceIndex);
        const y = this._decodeValue(g._cpu.y, g.yMeta, sourceIndex);
        const [px, py] = this._projectDataPoint(g.xAxis, g.yAxis, x, y, polarGeom);
        if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
        const sizeValue = g.sizeMode === 1 && g._cpu.size
          ? g.sizeRange[0] + (g.sizeRange[1] - g.sizeRange[0]) *
            (g._cpu.size instanceof Uint8Array
              ? g._cpu.size[sourceIndex] / 255
              : g._cpu.size[sourceIndex])
          : g.size;
        const size = Math.max(0, Number(sizeValue) * zoomStyle.sizeFactor);
        const rgba = this._authoredScatterRgba(g, sourceIndex, continuousLut, paletteRgba);
        const styleOffset = sourceIndex * 4;
        const itemStyle = g._cpuStyle && g._cpuStyle.length >= styleOffset + 4
          ? g._cpuStyle.subarray(styleOffset, styleOffset + 4)
          : null;
        const itemOpacity = itemStyle ? itemStyle[0] : 1;
        const scalarArtist = Number(style.artist_alpha);
        const artistAlpha = itemStyle && itemStyle[1] >= 0
          ? itemStyle[1]
          : Number.isFinite(scalarArtist) ? scalarArtist : -1;
        const intrinsicAlpha = artistAlpha >= 0 ? artistAlpha : rgba[3];
        const alpha = Math.max(
          0,
          Math.min(1, intrinsicAlpha * itemOpacity * zoomStyle.opacity * opacityScale),
        );
        const paint = `rgba(${Math.round(rgba[0] * 255)},${Math.round(rgba[1] * 255)},${Math.round(rgba[2] * 255)},${alpha})`;
        const strokeWidth = Math.max(
          0,
          itemStyle && itemStyle[2] >= 0
            ? itemStyle[2] / this.dpr
            : Number(style.stroke_width) || 0,
        );
        let strokeRgba = g.pointStroke || rgba;
        if (g._cpuStroke && g._cpuStroke.length >= (sourceIndex + 1) * 4) {
          const offset = sourceIndex * 4;
          strokeRgba = Array.from(
            g._cpuStroke.slice(offset, offset + 4),
            (value: number) => value / 255,
          );
        }
        const strokeIntrinsic = artistAlpha >= 0 ? artistAlpha : strokeRgba[3];
        const strokeAlpha = Math.max(
          0,
          Math.min(1, strokeIntrinsic * itemOpacity * zoomStyle.strokeOpacity * opacityScale),
        );
        const strokePaint = g.pointStrokeFace
          ? paint
          : `rgba(${Math.round(strokeRgba[0] * 255)},${Math.round(strokeRgba[1] * 255)},${Math.round(strokeRgba[2] * 255)},${strokeAlpha})`;
        const symbol = itemStyle && itemStyle[3] >= 0 ? Math.round(itemStyle[3]) : null;
        const diameter = Math.max(0, size - strokeWidth);
        ctx.save();
        ctx.fillStyle = paint;
        ctx.strokeStyle = strokePaint;
        ctx.lineWidth = strokeWidth;
        if (symbol !== null) {
          const lineSymbol = xyCanvasScatterSymbol(ctx, symbol, px, py, diameter);
          if (lineSymbol) {
            ctx.strokeStyle = paint;
            ctx.lineWidth = Math.max(1, strokeWidth);
            ctx.stroke();
          } else {
            ctx.fill("evenodd");
            if (strokeWidth > 0) ctx.stroke();
          }
        } else if (markerGlyph) {
          ctx.font = `${diameter}px "DejaVu Sans", sans-serif`;
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(String(markerGlyph), px, py);
          if (strokeWidth > 0) {
            ctx.strokeText(String(markerGlyph), px, py);
          }
        } else if (markerPath) {
          ctx.beginPath();
          for (const contour of markerPath.contours || []) {
            for (let offset = 0; offset + 1 < contour.length; offset += 2) {
              const vx = px + diameter * Number(contour[offset]);
              const vy = py - diameter * Number(contour[offset + 1]);
              if (offset === 0) ctx.moveTo(vx, vy);
              else ctx.lineTo(vx, vy);
            }
            if (markerPath.filled) ctx.closePath();
          }
          if (markerPath.filled) {
            ctx.fill("evenodd");
            if (strokeWidth > 0) ctx.stroke();
          } else {
            ctx.strokeStyle = paint;
            ctx.lineWidth = Math.max(1, strokeWidth);
            ctx.stroke();
          }
        }
        ctx.restore();
      }
    }
    ctx.restore();
  },

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
    const geom = xyArrowGeometry(x0, y0, x1, y1, style);
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
      let points = xyArrowShaftPoints(geom);
      if (headStyle === "triangle") {
        points = xyTrimPolylineEnd(points, head * Math.cos(Math.PI / 6));
      }
      const polygon = xyTaperPolygon(
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

  // A mark-owned annotation (a funnel's value/drop-off label) retires with
  // the geometry it describes: legend-hidden category, or hidden trace. An
  // author-written annotation carries no `owner` and is never suppressed.
  _annotationSuppressed(ann) {
    const owner = ann && ann.owner;
    if (!owner) return false;
    const traces = Array.isArray(this.spec.traces) ? this.spec.traces : [];
    const index = traces.findIndex((t) => t && t.id === owner.trace);
    if (index < 0) return false;
    if (this._legendOffTraces && this._legendOffTraces.has(index)) return true;
    const hidden = this._legendOffCats && this._legendOffCats.get(index);
    return !!(hidden && hidden.has(owner.category));
  },

  _drawAnnotationShapes(ctx) {
    const annotations = Array.isArray(this.spec.annotations) ? this.spec.annotations : [];
    if (!annotations.length) return;
    const p = this.plot;
    const polarGeom = this._polarGeometry();
    const project = (x, y) => this._projectDataPoint(
      "x",
      "y",
      Number(x),
      Number(y),
      polarGeom,
    );
    for (const [annotationIndex, ann] of annotations.entries()) {
      if (this._annotationSuppressed(ann)) continue;
      ctx.save();
      let targetX = NaN;
      let targetY = NaN;
      if (ann.kind === "arrow") {
        [targetX, targetY] = project(ann.x1, ann.y1);
      } else if (ann.kind === "callout") {
        [targetX, targetY] = project(ann.x, ann.y);
      }
      const connectorTargetInBounds =
        Number.isFinite(targetX) && Number.isFinite(targetY) &&
        targetX >= p.x && targetX <= p.x + p.w &&
        targetY >= p.y && targetY <= p.y + p.h;
      if (!connectorTargetInBounds) {
        if (polarGeom) {
          xyClipPolarCanvas(ctx, polarGeom);
        } else {
          ctx.beginPath();
          ctx.rect(p.x, p.y, p.w, p.h);
          ctx.clip();
        }
      }
      const style = ann && typeof ann.style === "object" ? ann.style : {};
      if (ann.kind === "band") {
        const vertical = ann.axis === "x";
        const a = vertical ? this._dataPxX(Number(ann.start)) : this._dataPxY(Number(ann.start));
        const b = vertical ? this._dataPxX(Number(ann.end)) : this._dataPxY(Number(ann.end));
        if (!Number.isFinite(a) || !Number.isFinite(b)) {
          ctx.restore();
          continue;
        }
        const lo = Math.max(vertical ? p.x : p.y, Math.min(a, b));
        const hi = Math.min(vertical ? p.x + p.w : p.y + p.h, Math.max(a, b));
        if (hi <= lo) {
          ctx.restore();
          continue;
        }
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
        if (!Number.isFinite(pos)) {
          ctx.restore();
          continue;
        }
        if (vertical && (pos < p.x - 1 || pos > p.x + p.w + 1)) {
          ctx.restore();
          continue;
        }
        if (!vertical && (pos < p.y - 1 || pos > p.y + p.h + 1)) {
          ctx.restore();
          continue;
        }
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
        const [arrowX0, arrowY0] = this._dataPxPoint(Number(ann.x0), Number(ann.y0));
        const [arrowX1, arrowY1] = this._dataPxPoint(Number(ann.x1), Number(ann.y1));
        this._drawArrowLine(ctx, arrowX0, arrowY0, arrowX1, arrowY1, style);
      } else if (ann.kind === "callout") {
        const [px, py] = project(ann.x, ann.y);
        const resolved = this._resolvedAnnotationAnchors?.get(annotationIndex);
        const dx = Number.isFinite(Number(ann.dx)) ? Number(ann.dx) : 0;
        const dy = Number.isFinite(Number(ann.dy)) ? Number(ann.dy) : 0;
        // DOM label layout is throttled during view animations. Keep the
        // pointer attached to the label that is actually visible rather than
        // applying its previous relative offset to the current data position.
        const labelX = resolved?.x ?? px + dx;
        const labelY = resolved?.y ?? py + dy;
        this._drawArrowLine(ctx, labelX, labelY, px, py, style);
      } else if (ann.kind === "marker") {
        const [markerX, markerY] = this._dataPxPoint(Number(ann.x), Number(ann.y));
        this._drawAnnotationMarker(ctx, markerX, markerY, style, ann);
      }
      ctx.restore();
    }
  },

  _drawAnnotationLabels(updateLabels) {
    if (!updateLabels) return;
    const annotations = Array.isArray(this.spec.annotations) ? this.spec.annotations : [];
    if (!annotations.length) return;
    const p = this.plot;
    const laidOut = [];
    this._resolvedAnnotationAnchors = new Map();
    for (const [annotationIndex, ann] of annotations.entries()) {
      const text: string = typeof ann.text === "string" ? ann.text : "";
      if (!text || this._annotationSuppressed(ann)) continue;
      const style = ann && typeof ann.style === "object" ? ann.style : {};
      let px = null;
      let py = null;
      let lift = null;
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
          [px, py] = this._dataPxPoint(Number(ann.x), Number(ann.y));
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
        const [ax0, ay0] = this._dataPxPoint(Number(ann.x0), Number(ann.y0));
        const [ax1, ay1] = this._dataPxPoint(Number(ann.x1), Number(ann.y1));
        px = (ax0 + ax1) / 2;
        py = (ay0 + ay1) / 2;
        // Upward unit normal of the shaft: the label lifts along it (after
        // measuring, below) so the line doesn't strike through the word.
        const len = Math.hypot(ax1 - ax0, ay1 - ay0);
        if (len > 1e-6) {
          lift = [-(ay1 - ay0) / len, (ax1 - ax0) / len];
          if (lift[1] > 0) lift = [-lift[0], -lift[1]];
        }
      } else if (ann.kind === "callout" || ann.kind === "marker") {
        [px, py] = this._dataPxPoint(Number(ann.x), Number(ann.y));
      }
      if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
      if (px < p.x - 24 || px > p.x + p.w + 24 || py < p.y - 24 || py > p.y + p.h + 24) {
        continue;
      }
      const d = document.createElement("div");
      const mathRanges = String(style.math_italic_ranges || "")
        .split(",")
        .map((range) => range.split(":").map(Number))
        .filter(([start, end]) => Number.isInteger(start) && Number.isInteger(end) && start >= 0 && start < end);
      if (mathRanges.length) {
        for (const [index, char] of Array.from(text).entries()) {
          if (mathRanges.some(([start, end]) => start <= index && index < end)) {
            const italic = document.createElement("span");
            italic.style.fontStyle = "italic";
            italic.textContent = char;
            d.appendChild(italic);
          } else {
            d.appendChild(document.createTextNode(char));
          }
        }
      } else {
        d.textContent = text;
      }
      const dx = Number.isFinite(Number(ann.dx)) ? Number(ann.dx) : 0;
      const dy = Number.isFinite(Number(ann.dy)) ? Number(ann.dy) : 0;
      // Rule/band specs carry no anchor; default to the placement that keeps
      // the badge inside the plot: y labels sit at the right edge and must
      // grow LEFT, x labels sit at the top edge and must hang DOWN (band text
      // centered on the band, y-band text centered on its span).
      let anchorName = ann.anchor;
      let va = String(style.vertical_align || "");
      if (ann.kind === "rule" || ann.kind === "band") {
        if (ann.axis === "x") {
          if (!anchorName && ann.kind === "band") anchorName = "middle";
          if (!va) va = "top";
        } else {
          if (!anchorName) anchorName = "end";
          if (!va && ann.kind === "band") va = "middle";
        }
      } else if (ann.kind === "arrow") {
        // Centered on the shaft midpoint, then lifted clear of the line.
        if (!anchorName) anchorName = "middle";
        if (!va) va = "middle";
      }
      const anchor = anchorName === "middle" ? "-50%" : anchorName === "end" ? "-100%" : "0px";
      const rot = Number.isFinite(Number(style.rotation))
        ? ((Number(style.rotation) % 360) + 360) % 360
        : 0;
      // matplotlib's va, matching the SVG/raster exporters: the default is
      // the text BASELINE at the anchor (~0.35em of descent hangs below it),
      // not the box top.
      const vAnchor =
        va === "center" || va === "middle" ? "-50%"
          : va === "bottom" ? "-100%"
          : va === "top" ? "0px"
          : "calc(-100% + 0.35em)";
      // mpl rotation is CCW; CSS rotate is CW. For vertical text mpl aligns
      // the post-rotation box: vertical_align picks the along-reading offset,
      // the anchor the cross-axis one (translate runs first, in the element's
      // own frame, so percentages track its box).
      let transform = `translate(${anchor},${vAnchor})`;
      if (rot === 90 || rot === 270) {
        const cw = rot === 270;
        const along =
          va === "center" || va === "middle" ? "-50%"
          : va === "top" ? (cw ? "0" : "-100%")
          : va === "bottom" ? (cw ? "-100%" : "0")
          : cw ? "0" : "-100%";
        const cross =
          anchorName === "middle" ? "-50%" : anchorName === "end" ? (cw ? "0" : "-100%") : cw ? "-100%" : "0";
        transform = `rotate(${cw ? 90 : -90}deg) translate(${along},${cross})`;
      } else if (rot) {
        transform = `rotate(${-rot}deg) translate(${anchor},${vAnchor})`;
      }
      // Structural inline only (position telegraphs the anchor); font + default
      // color live in the defeatable :where() stylesheet so utility classes win.
      // width:max-content: shrink-to-fit for an absolutely positioned label is
      // capped by the distance to the containing block's edge, so an end/middle
      // anchored label near the right edge would wrap word-per-word BEFORE the
      // translate(-100%) shift moves it back inside.
      d.style.cssText =
        `position:absolute;left:${px + dx}px;top:${py + dy}px;` +
        `transform:${transform};transform-origin:0 0;pointer-events:none;` +
        `white-space:pre-line;text-align:center;width:max-content;`;
      this._applySlot(d, "annotation_label");
      this._applyClass(d, ann.class_name);
      // Shape-geometry/paint keys style the canvas shape, not the label DOM —
      // e.g. an arrow's shaft `width` must not become CSS width on the label.
      // Likewise `opacity` on a shape-bearing annotation is the band fill /
      // rule stroke / arrow / marker alpha (exporter semantics), not a label
      // dimmer; only text/callout labels own their opacity.
      const opacityIsShape = ann.kind !== "text" && ann.kind !== "callout";
      const labelStyle = {};
      for (const [key, value] of Object.entries(style)) {
        if (key === "math_italic_ranges") continue;
        if (key === "opacity" && ann.kind === "text") {
          labelStyle[key] = value;
          continue;
        }
        if (XY_ANNOTATION_SHAPE_STYLE_KEYS.has(key)) continue;
        if (opacityIsShape && key === "opacity") continue;
        labelStyle[key] = value;
      }
      this._applyStyle(d, labelStyle);
      // Only pin color inline when the annotation asked for one — otherwise the
      // stylesheet's --chart-annotation-text default stays overridable by CSS.
      if (style && (style.label_color || style.color)) {
        d.style.color = this._annotationLabelPaint(style, this.theme.label);
      }
      if (style && style.label_opacity !== undefined) {
        const labelOpacity = Number(style.label_opacity);
        if (Number.isFinite(labelOpacity)) {
          d.style.opacity = String(Math.max(0, Math.min(1, labelOpacity)));
        }
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
      // Vertical (90/270) labels translate by along/cross, not anchor/vAnchor,
      // so the text-edge shift below doesn't apply; they keep box-edge anchoring.
      if ((padL || padR || padT || padB) && rot !== 90 && rot !== 270) {
        const hShift = anchor === "-100%" ? padR : anchor === "-50%" ? 0 : -padL;
        // Bottom-referenced anchors (bottom, and the baseline default) ride
        // up as bottom padding grows; top-referenced ones ride down.
        const vShift =
          vAnchor === "-50%" ? 0 : vAnchor === "0px" ? -padT : padB;
        // The shift happens in the label's own (possibly rotated) frame, so a
        // rotate prefix composes: keep it rather than clobbering it.
        d.style.transform =
          `${rot ? `rotate(${-rot}deg) ` : ""}` +
          `translate(calc(${anchor} + ${hShift}px), calc(${vAnchor} + ${vShift}px))`;
      }
      // Arrow labels sit at the shaft midpoint; push the box out along the
      // shaft's upward normal until it clears the (possibly slanted) line —
      // a fixed offset alone still lets a wide word's far end hit the shaft.
      // Client-only geometry: the exporters do not render arrow labels.
      const liftBounds = lift && this.labels.getBoundingClientRect();
      if (lift && liftBounds.width > 0) {
        const liftScale = liftBounds.width / this.size.w;
        const r = d.getBoundingClientRect();
        const clear =
          (r.width / liftScale / 2) * Math.abs(lift[0]) +
          (r.height / liftScale / 2) * Math.abs(lift[1]) + 3;
        px += lift[0] * clear;
        py += lift[1] * clear;
        d.style.left = `${px + dx}px`;
        d.style.top = `${py + dy}px`;
      }
      // A label anchored at a plot edge (or pushed out by dx/padding) must
      // never overflow the figure: measure the laid-out box and pull it back
      // inside. Rects are in visual px, left/top in figure px — rescale.
      const bounds = this.labels.getBoundingClientRect();
      if (bounds.width > 0) {
        const scale = bounds.width / this.size.w;
        const r = d.getBoundingClientRect();
        const pullX =
          r.right > bounds.right ? bounds.right - r.right
          : r.left < bounds.left ? bounds.left - r.left : 0;
        const pullY =
          r.bottom > bounds.bottom ? bounds.bottom - r.bottom
          : r.top < bounds.top ? bounds.top - r.top : 0;
        if (pullX) d.style.left = `${px + dx + pullX / scale}px`;
        if (pullY) d.style.top = `${py + dy + pullY / scale}px`;
      }
      laidOut.push({ d, ann, annotationIndex, px, py });
    }

    // Explicitly positioned labels are obstacles, not candidates for automatic
    // staggering. Auto rule/band labels then take deterministic rows/columns,
    // which avoids resize flashing and preserves user-provided anchor/offsets.
    const bounds = this.labels.getBoundingClientRect();
    if (bounds.width > 0 && bounds.height > 0) {
      const scaleX = bounds.width / this.size.w;
      const scaleY = bounds.height / this.size.h;
      const occupied = [];
      const automatic = (item) =>
        (item.ann.kind === "rule" || item.ann.kind === "band") &&
        item.ann.anchor === undefined && item.ann.dx === undefined && item.ann.dy === undefined;
      const ordered = [...laidOut].sort((a, b) => Number(automatic(a)) - Number(automatic(b)));
      const overlaps = (a, b) =>
        a.left < b.right + 3 && a.right > b.left - 3 &&
        a.top < b.bottom + 3 && a.bottom > b.top - 3;
      const inside = (rect) =>
        rect.left >= bounds.left - 0.5 && rect.right <= bounds.right + 0.5 &&
        rect.top >= bounds.top - 0.5 && rect.bottom <= bounds.bottom + 0.5;
      const shifted = (rect, dx, dy) => ({
        left: rect.left + dx,
        right: rect.right + dx,
        top: rect.top + dy,
        bottom: rect.bottom + dy,
        width: rect.width,
        height: rect.height,
      });
      for (const item of ordered) {
        const baseLeft = parseFloat(item.d.style.left) || 0;
        const baseTop = parseFloat(item.d.style.top) || 0;
        let finalRect = item.d.getBoundingClientRect();
        if (automatic(item)) {
          const step = (item.ann.axis === "x" ? finalRect.height : finalRect.width) + 5;
          const candidates = [0];
          for (let row = 1; row <= 12; row++) candidates.push(row, -row);
          let placed = false;
          for (const candidate of candidates) {
            const dx = item.ann.axis === "x" ? 0 : candidate * step;
            const dy = item.ann.axis === "x" ? candidate * step : 0;
            const candidateRect = shifted(finalRect, dx, dy);
            if (inside(candidateRect) && !occupied.some((other) => overlaps(candidateRect, other))) {
              if (dx) item.d.style.left = `${baseLeft + dx / scaleX}px`;
              if (dy) item.d.style.top = `${baseTop + dy / scaleY}px`;
              finalRect = candidateRect;
              placed = true;
              break;
            }
          }
          if (!placed) {
            item.d.style.left = `${baseLeft}px`;
            item.d.style.top = `${baseTop}px`;
          }
        }
        occupied.push(finalRect);
      }
    }

    // The pointer begins at the callout's final text anchor. Cache its absolute
    // position so animation frames that throttle DOM layout keep pointing at
    // the label that remains visible, even while its data coordinate moves.
    for (const item of laidOut) {
      if (item.ann.kind !== "callout") continue;
      const left = parseFloat(item.d.style.left);
      const top = parseFloat(item.d.style.top);
      const dx = Number.isFinite(Number(item.ann.dx)) ? Number(item.ann.dx) : 0;
      const dy = Number.isFinite(Number(item.ann.dy)) ? Number(item.ann.dy) : 0;
      this._resolvedAnnotationAnchors.set(item.annotationIndex, {
        x: Number.isFinite(left) ? left : item.px + dx,
        y: Number.isFinite(top) ? top : item.py + dy,
      });
    }
  },
});
