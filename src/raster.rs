//! Anti-aliased 2D rasterizer for the native PNG export path
//! (design dossier Phase 3). Python computes all chart geometry (reusing the SVG
//! exporter's scales/ticks/colormaps) and hands over a flat *display list* — a
//! tagged command stream — which this module paints into a straight-alpha RGBA8
//! framebuffer the caller owns.
//!
//! Shapes are tessellated to polygons on the Python side, so the core here is a
//! small, general set: coverage-based scanline **polygon fill** (flat + linear
//! gradient), distance-based **stroke** and **point/symbol** rasterization (which
//! gets round caps/joins and AA for free), **image blit** (density/heatmap
//! rasters), and **text** blitted from the baked font atlas (`font.rs`). PNG
//! compression uses `png`/fdeflate; text needs no FreeType.

use crate::font;
use std::io::Cursor;

// ---- command opcodes (must match python/xy/_raster.py) --------------
const OP_CLIP: u8 = 0;
const OP_FILL_POLY: u8 = 1;
const OP_FILL_POLY_GRAD: u8 = 2;
const OP_STROKE: u8 = 3;
const OP_POINT: u8 = 4;
const OP_IMAGE: u8 = 5;
const OP_TEXT: u8 = 6;
const OP_POINTS: u8 = 7;
const OP_SEGMENTS: u8 = 8;

const SS: usize = 4; // vertical supersamples per scanline for polygon AA

/// Straight-alpha RGBA8 framebuffer. Static chart export paints an opaque
/// background first, so keeping the working canvas in its final byte format
/// avoids a 16-byte-per-pixel float canvas plus a full-frame conversion pass.
/// The generic translucent-destination branch preserves correct source-over
/// behavior for direct rasterizer callers that do not begin with a background.
struct Canvas {
    w: usize,
    h: usize,
    px: Vec<u8>,
    opaque: bool,
    clip: [f32; 4], // x0, y0, x1, y1
}

impl Canvas {
    fn new(w: usize, h: usize, opaque_white: bool) -> Self {
        let channels = if opaque_white { 3 } else { 4 };
        Canvas {
            w,
            h,
            px: vec![if opaque_white { 255 } else { 0 }; w * h * channels],
            opaque: opaque_white,
            clip: [0.0, 0.0, w as f32, h as f32],
        }
    }

    #[inline]
    fn channels(&self) -> usize {
        if self.opaque {
            3
        } else {
            4
        }
    }

    #[inline]
    fn blend(&mut self, x: usize, y: usize, rgba: [f32; 4], cov: f32) {
        self.blend_u8(
            x,
            y,
            [
                to_u8(rgba[0]),
                to_u8(rgba[1]),
                to_u8(rgba[2]),
                to_u8(rgba[3] * cov),
            ],
        );
    }

    #[inline]
    fn blend_u8(&mut self, x: usize, y: usize, rgba: [u8; 4]) {
        let sa = rgba[3] as u32;
        if sa == 0 {
            return;
        }
        let src = [rgba[0] as u32, rgba[1] as u32, rgba[2] as u32];
        let o = (y * self.w + x) * self.channels();
        if self.opaque {
            if sa == 255 {
                self.px[o] = src[0] as u8;
                self.px[o + 1] = src[1] as u8;
                self.px[o + 2] = src[2] as u8;
            } else {
                let inv = 255 - sa;
                for (k, source) in src.iter().enumerate() {
                    self.px[o + k] =
                        ((*source * sa + self.px[o + k] as u32 * inv + 127) / 255) as u8;
                }
            }
            return;
        }
        if sa == 255 {
            self.px[o] = src[0] as u8;
            self.px[o + 1] = src[1] as u8;
            self.px[o + 2] = src[2] as u8;
            self.px[o + 3] = 255;
            return;
        }
        let da = self.px[o + 3] as u32;
        let inv = 255 - sa;
        if da == 255 {
            for (k, source) in src.iter().enumerate() {
                self.px[o + k] = ((*source * sa + self.px[o + k] as u32 * inv + 127) / 255) as u8;
            }
            return;
        }
        let out_a_num = sa * 255 + da * inv;
        if out_a_num == 0 {
            return;
        }
        for (k, source) in src.iter().enumerate() {
            let num = *source * sa * 255 + self.px[o + k] as u32 * da * inv;
            self.px[o + k] = ((num + out_a_num / 2) / out_a_num) as u8;
        }
        self.px[o + 3] = ((out_a_num + 127) / 255) as u8;
    }

    /// Clip∩canvas pixel bbox for a float rect, as inclusive-exclusive ranges.
    fn bbox(&self, x0: f32, y0: f32, x1: f32, y1: f32) -> (usize, usize, usize, usize) {
        let cx0 = x0.max(self.clip[0]).max(0.0);
        let cy0 = y0.max(self.clip[1]).max(0.0);
        let cx1 = x1.min(self.clip[2]).min(self.w as f32);
        let cy1 = y1.min(self.clip[3]).min(self.h as f32);
        if cx1 <= cx0 || cy1 <= cy0 {
            return (0, 0, 0, 0);
        }
        (
            cx0.floor() as usize,
            cy0.floor() as usize,
            (cx1.ceil() as usize).min(self.w),
            (cy1.ceil() as usize).min(self.h),
        )
    }

    /// Export to straight-alpha RGBA8.
    fn to_rgba8(&self, out: &mut [u8]) {
        if self.opaque {
            for (rgb, rgba) in self.px.chunks_exact(3).zip(out.chunks_exact_mut(4)) {
                rgba[..3].copy_from_slice(rgb);
                rgba[3] = 255;
            }
        } else {
            out.copy_from_slice(&self.px);
        }
    }
}

fn stroke_segment(cv: &mut Canvas, a: (f32, f32), b: (f32, f32), width: f32, rgba: [f32; 4]) {
    if width <= 0.0 {
        return;
    }
    let hw = width * 0.5;
    let (bx0, by0, bx1, by1) = cv.bbox(
        a.0.min(b.0) - hw - 1.0,
        a.1.min(b.1) - hw - 1.0,
        a.0.max(b.0) + hw + 1.0,
        a.1.max(b.1) + hw + 1.0,
    );
    let (dx, dy) = (b.0 - a.0, b.1 - a.1);
    if dx.abs() >= dy.abs() && dx.abs() > 1e-6 {
        for x in bx0..bx1 {
            let t = ((x as f32 + 0.5 - a.0) / dx).clamp(0.0, 1.0);
            let center = a.1 + t * dy;
            let sy0 = ((center - hw - 1.0).floor() as usize).max(by0);
            let sy1 = ((center + hw + 1.0).ceil() as usize).min(by1);
            for y in sy0..sy1 {
                let cov = seg_coverage((x as f32 + 0.5, y as f32 + 0.5), a, b, hw);
                if cov > 0.0 {
                    cv.blend(x, y, rgba, cov);
                }
            }
        }
    } else if dy.abs() > 1e-6 {
        for y in by0..by1 {
            let t = ((y as f32 + 0.5 - a.1) / dy).clamp(0.0, 1.0);
            let center = a.0 + t * dx;
            let sx0 = ((center - hw - 1.0).floor() as usize).max(bx0);
            let sx1 = ((center + hw + 1.0).ceil() as usize).min(bx1);
            for x in sx0..sx1 {
                let cov = seg_coverage((x as f32 + 0.5, y as f32 + 0.5), a, b, hw);
                if cov > 0.0 {
                    cv.blend(x, y, rgba, cov);
                }
            }
        }
    } else {
        for y in by0..by1 {
            for x in bx0..bx1 {
                let cov = seg_coverage((x as f32 + 0.5, y as f32 + 0.5), a, b, hw);
                if cov > 0.0 {
                    cv.blend(x, y, rgba, cov);
                }
            }
        }
    }
}

#[inline]
fn to_u8(v: f32) -> u8 {
    (v.clamp(0.0, 1.0) * 255.0 + 0.5) as u8
}

/// Fast analytic path for the overwhelmingly common axis-aligned rectangle.
/// It is exact at subpixel edges and turns the full-canvas white background
/// from millions of polygon-coverage blends into a contiguous byte fill.
fn fill_rect(cv: &mut Canvas, pts: &[(f32, f32)], rgba: [f32; 4]) -> bool {
    if pts.len() != 4 {
        return false;
    }
    let mut xs = [pts[0].0, pts[1].0, pts[2].0, pts[3].0];
    let mut ys = [pts[0].1, pts[1].1, pts[2].1, pts[3].1];
    xs.sort_by(f32::total_cmp);
    ys.sort_by(f32::total_cmp);
    let (x0, x1, y0, y1) = (xs[0], xs[3], ys[0], ys[3]);
    let eps = 1e-4;
    if xs[1] - x0 > eps || x1 - xs[2] > eps || ys[1] - y0 > eps || y1 - ys[2] > eps {
        return false;
    }
    let (bx0, by0, bx1, by1) = cv.bbox(x0, y0, x1, y1);
    if bx1 <= bx0 || by1 <= by0 {
        return true;
    }
    if rgba[3] >= 1.0
        && x0 <= bx0 as f32
        && y0 <= by0 as f32
        && x1 >= bx1 as f32
        && y1 >= by1 as f32
    {
        let rgba8 = [to_u8(rgba[0]), to_u8(rgba[1]), to_u8(rgba[2]), 255];
        let channels = cv.channels();
        let color = &rgba8[..channels];
        for y in by0..by1 {
            let row = &mut cv.px[(y * cv.w + bx0) * channels..(y * cv.w + bx1) * channels];
            if color.iter().all(|channel| *channel == color[0]) {
                row.fill(color[0]);
            } else {
                for pixel in row.chunks_exact_mut(channels) {
                    pixel.copy_from_slice(color);
                }
            }
        }
        return true;
    }
    for y in by0..by1 {
        let cy = ((y + 1) as f32).min(y1) - (y as f32).max(y0);
        for x in bx0..bx1 {
            let cx = ((x + 1) as f32).min(x1) - (x as f32).max(x0);
            cv.blend(x, y, rgba, (cx * cy).clamp(0.0, 1.0));
        }
    }
    true
}

// ---- polygon fill (coverage scanline) ---------------------------------------

/// Per-row coverage in [0,1] over the polygon's x-span, with `color_at` giving
/// the paint per pixel (flat or gradient). Non-zero winding, `SS` vertical
/// samples, analytic horizontal endpoint coverage.
fn fill_poly(cv: &mut Canvas, pts: &[(f32, f32)], mut color_at: impl FnMut(f32, f32) -> [f32; 4]) {
    if pts.len() < 3 {
        return;
    }
    let mut ymin = f32::INFINITY;
    let mut ymax = f32::NEG_INFINITY;
    let mut xmin = f32::INFINITY;
    let mut xmax = f32::NEG_INFINITY;
    for &(x, y) in pts {
        ymin = ymin.min(y);
        ymax = ymax.max(y);
        xmin = xmin.min(x);
        xmax = xmax.max(x);
    }
    let (bx0, by0, bx1, by1) = cv.bbox(xmin, ymin, xmax, ymax);
    if bx1 <= bx0 {
        return;
    }
    let row_w = bx1 - bx0;
    let mut cov = vec![0.0f32; row_w];
    let mut xs: Vec<(f32, i32)> = Vec::with_capacity(pts.len());

    for y in by0..by1 {
        for c in cov.iter_mut() {
            *c = 0.0;
        }
        for s in 0..SS {
            let sy = y as f32 + (s as f32 + 0.5) / SS as f32;
            xs.clear();
            let n = pts.len();
            for i in 0..n {
                let (x0, y0) = pts[i];
                let (x1, y1) = pts[(i + 1) % n];
                if (y0 <= sy && y1 > sy) || (y1 <= sy && y0 > sy) {
                    let t = (sy - y0) / (y1 - y0);
                    let x = x0 + t * (x1 - x0);
                    xs.push((x, if y1 > y0 { 1 } else { -1 }));
                }
            }
            if xs.len() < 2 {
                continue;
            }
            xs.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
            let mut wind = 0;
            for i in 0..xs.len() - 1 {
                wind += xs[i].1;
                if wind == 0 {
                    continue;
                }
                let xa = xs[i].0.max(bx0 as f32);
                let xb = xs[i + 1].0.min(bx1 as f32);
                if xb <= xa {
                    continue;
                }
                let px0 = xa.floor() as usize;
                let px1 = (xb.ceil() as usize).min(bx1);
                for px in px0..px1 {
                    let l = xa.max(px as f32);
                    let r = xb.min((px + 1) as f32);
                    if r > l {
                        cov[px - bx0] += (r - l) / SS as f32;
                    }
                }
            }
        }
        for (i, &c) in cov.iter().enumerate() {
            if c > 0.0 {
                let x = bx0 + i;
                cv.blend(x, y, color_at(x as f32 + 0.5, y as f32 + 0.5), c.min(1.0));
            }
        }
    }
}

// ---- stroke (distance field, round caps/joins) ------------------------------

#[inline]
fn seg_dist2(p: (f32, f32), a: (f32, f32), b: (f32, f32)) -> f32 {
    let (px, py) = p;
    let (ax, ay) = a;
    let (bx, by) = b;
    let (dx, dy) = (bx - ax, by - ay);
    let len2 = dx * dx + dy * dy;
    let t = if len2 <= 1e-12 {
        0.0
    } else {
        (((px - ax) * dx + (py - ay) * dy) / len2).clamp(0.0, 1.0)
    };
    let (cx, cy) = (ax + t * dx, ay + t * dy);
    (px - cx).powi(2) + (py - cy).powi(2)
}

#[inline]
fn seg_coverage(p: (f32, f32), a: (f32, f32), b: (f32, f32), hw: f32) -> f32 {
    let distance2 = seg_dist2(p, a, b);
    let outer = hw + 0.5;
    if distance2 >= outer * outer {
        return 0.0;
    }
    let inner = (hw - 0.5).max(0.0);
    if distance2 <= inner * inner {
        return 1.0;
    }
    outer - distance2.sqrt()
}

/// Rasterize on-segments into a scratch coverage buffer (max-combined so
/// overlapping joins don't double-darken), then composite once.
fn stroke(
    cv: &mut Canvas,
    pts: &[(f32, f32)],
    width: f32,
    rgba: [f32; 4],
    closed: bool,
    dash: &[f32],
) {
    if pts.len() < 2 || width <= 0.0 {
        return;
    }
    if pts.len() == 2 && !closed && dash.is_empty() {
        stroke_segment(cv, pts[0], pts[1], width, rgba);
        return;
    }
    let hw = width * 0.5;
    let mut segs: Vec<((f32, f32), (f32, f32))> = Vec::new();
    let n = pts.len();
    let last = if closed { n } else { n - 1 };
    let raw: Vec<((f32, f32), (f32, f32))> =
        (0..last).map(|i| (pts[i], pts[(i + 1) % n])).collect();

    if dash.is_empty() {
        segs = raw;
    } else {
        // Walk arc length toggling on/off through the dash pattern.
        let total: f32 = dash.iter().sum();
        if total <= 0.0 {
            segs = raw;
        } else {
            let mut di = 0usize;
            let mut drem = dash[0];
            let mut on = true;
            for (a, b) in raw {
                let (mut ax, mut ay) = a;
                let seglen = ((b.0 - ax).powi(2) + (b.1 - ay).powi(2)).sqrt();
                let mut remain = seglen;
                if seglen <= 1e-9 {
                    continue;
                }
                let (ux, uy) = ((b.0 - a.0) / seglen, (b.1 - a.1) / seglen);
                while remain > 1e-6 {
                    let step = drem.min(remain);
                    let (nx, ny) = (ax + ux * step, ay + uy * step);
                    if on {
                        segs.push(((ax, ay), (nx, ny)));
                    }
                    ax = nx;
                    ay = ny;
                    remain -= step;
                    drem -= step;
                    if drem <= 1e-6 {
                        di = (di + 1) % dash.len();
                        drem = dash[di];
                        on = !on;
                    }
                }
            }
        }
    }
    if segs.is_empty() {
        return;
    }

    let mut xmin = f32::INFINITY;
    let mut ymin = f32::INFINITY;
    let mut xmax = f32::NEG_INFINITY;
    let mut ymax = f32::NEG_INFINITY;
    for (a, b) in &segs {
        xmin = xmin.min(a.0.min(b.0));
        ymin = ymin.min(a.1.min(b.1));
        xmax = xmax.max(a.0.max(b.0));
        ymax = ymax.max(a.1.max(b.1));
    }
    let (bx0, by0, bx1, by1) = cv.bbox(
        xmin - hw - 1.0,
        ymin - hw - 1.0,
        xmax + hw + 1.0,
        ymax + hw + 1.0,
    );
    if bx1 <= bx0 {
        return;
    }
    let (sw, sh) = (bx1 - bx0, by1 - by0);
    let mut scratch = vec![0u8; sw * sh];
    for (a, b) in &segs {
        let sx0 = ((a.0.min(b.0) - hw - 1.0).floor() as usize).max(bx0);
        let sy0 = ((a.1.min(b.1) - hw - 1.0).floor() as usize).max(by0);
        let sx1 = ((a.0.max(b.0) + hw + 1.0).ceil() as usize).min(bx1);
        let sy1 = ((a.1.max(b.1) + hw + 1.0).ceil() as usize).min(by1);
        for y in sy0..sy1 {
            for x in sx0..sx1 {
                let c = seg_coverage((x as f32 + 0.5, y as f32 + 0.5), *a, *b, hw);
                if c > 0.0 {
                    let s = &mut scratch[(y - by0) * sw + (x - bx0)];
                    let coverage = to_u8(c);
                    if coverage > *s {
                        *s = coverage;
                    }
                }
            }
        }
    }
    for y in by0..by1 {
        for x in bx0..bx1 {
            let c = scratch[(y - by0) * sw + (x - bx0)];
            if c > 0 {
                cv.blend(x, y, rgba, c as f32 / 255.0);
            }
        }
    }
}

// ---- point / symbol (signed distance field) ---------------------------------

#[inline]
fn symbol_sdf(px: f32, py: f32, r: f32, sym: u8) -> f32 {
    match sym {
        1 => px.abs().max(py.abs()) - r, // square
        2 => (px.abs() + py.abs()) - r,  // diamond
        3 => {
            // equilateral triangle, apex up (IQ SDF), matching the GL shader
            let k = 1.732_050_8_f32;
            let rr = r * 1.24;
            let mut p = (px, -py);
            p.0 = p.0.abs() - rr;
            p.1 += rr / k;
            if p.0 + k * p.1 > 0.0 {
                p = ((p.0 - k * p.1) / 2.0, (-k * p.0 - p.1) / 2.0);
            }
            p.0 -= p.0.clamp(-2.0 * rr, 0.0);
            -(p.0 * p.0 + p.1 * p.1).sqrt() * p.1.signum()
        }
        4 => {
            // plus / cross
            let (ax, ay) = (px.abs(), py.abs());
            (ax - 0.34 * r).max(ay - r).min((ax - r).max(ay - 0.34 * r))
        }
        _ => (px * px + py * py).sqrt() - r, // circle
    }
}

#[allow(clippy::too_many_arguments)]
fn point(
    cv: &mut Canvas,
    cx: f32,
    cy: f32,
    r: f32,
    sym: u8,
    fill: [f32; 4],
    sw: f32,
    stroke: [f32; 4],
) {
    let ext = r + sw + 1.0;
    let (bx0, by0, bx1, by1) = cv.bbox(cx - ext, cy - ext, cx + ext, cy + ext);
    for y in by0..by1 {
        for x in bx0..bx1 {
            let d = symbol_sdf(x as f32 + 0.5 - cx, y as f32 + 0.5 - cy, r, sym);
            if sw > 0.0 {
                let outer = (0.5 - (d - sw * 0.5)).clamp(0.0, 1.0);
                let inner = (0.5 - (d + sw * 0.5)).clamp(0.0, 1.0);
                if inner > 0.0 {
                    cv.blend(x, y, fill, inner);
                }
                let ring = outer - inner;
                if ring > 0.0 {
                    cv.blend(x, y, stroke, ring);
                }
            } else {
                let c = (0.5 - d).clamp(0.0, 1.0);
                if c > 0.0 {
                    cv.blend(x, y, fill, c);
                }
            }
        }
    }
}

// ---- image blit -------------------------------------------------------------

#[allow(clippy::too_many_arguments)]
fn blit(
    cv: &mut Canvas,
    dx: f32,
    dy: f32,
    dw: f32,
    dh: f32,
    iw: usize,
    ih: usize,
    src: &[u8],
    nearest: bool,
) {
    if iw == 0 || ih == 0 || dw <= 0.0 || dh <= 0.0 {
        return;
    }
    let (bx0, by0, bx1, by1) = cv.bbox(dx, dy, dx + dw, dy + dh);
    if nearest {
        let xmap: Vec<usize> = (bx0..bx1)
            .map(|x| (((x as f32 + 0.5 - dx) / dw * iw as f32).floor() as usize).min(iw - 1))
            .collect();
        for y in by0..by1 {
            let sy = (((y as f32 + 0.5 - dy) / dh * ih as f32).floor() as usize).min(ih - 1);
            for (offset, &sx) in xmap.iter().enumerate() {
                let source = (sy * iw + sx) * 4;
                let color = [
                    src[source],
                    src[source + 1],
                    src[source + 2],
                    src[source + 3],
                ];
                cv.blend_u8(bx0 + offset, y, color);
            }
        }
        return;
    }
    let sample = |sx: usize, sy: usize, k: usize| src[(sy * iw + sx) * 4 + k] as f32 / 255.0;
    for y in by0..by1 {
        for x in bx0..bx1 {
            let u = ((x as f32 + 0.5 - dx) / dw * iw as f32 - 0.5).clamp(0.0, iw as f32 - 1.0);
            let v = ((y as f32 + 0.5 - dy) / dh * ih as f32 - 0.5).clamp(0.0, ih as f32 - 1.0);
            let (x0, y0) = (u.floor() as usize, v.floor() as usize);
            let (x1, y1) = ((x0 + 1).min(iw - 1), (y0 + 1).min(ih - 1));
            let (fx, fy) = (u - x0 as f32, v - y0 as f32);
            let w00 = (1.0 - fx) * (1.0 - fy);
            let w10 = fx * (1.0 - fy);
            let w01 = (1.0 - fx) * fy;
            let w11 = fx * fy;
            let mut c = [0.0f32; 4];
            for (k, ck) in c.iter_mut().enumerate() {
                *ck = w00 * sample(x0, y0, k)
                    + w10 * sample(x1, y0, k)
                    + w01 * sample(x0, y1, k)
                    + w11 * sample(x1, y1, k);
            }
            cv.blend(x, y, c, 1.0);
        }
    }
}

// ---- text (baked glyph atlas) -----------------------------------------------

fn text(cv: &mut Canvas, x: f32, y: f32, anchor: u8, size: f32, rgba: [f32; 4], s: &[u8]) {
    let scale = size / font::BASE_PX as f32;
    // Total advance for anchoring.
    let mut adv = 0.0f32;
    for &b in s {
        if (font::FIRST..=font::LAST).contains(&b) {
            adv += font::GLYPHS[(b - font::FIRST) as usize].0 as f32;
        }
    }
    let mut penx = match anchor {
        1 => x - adv * scale * 0.5,
        2 => x - adv * scale,
        _ => x,
    };
    for &b in s {
        if !(font::FIRST..=font::LAST).contains(&b) {
            continue;
        }
        let (advance, gw, gh, left, top, off, len) = font::GLYPHS[(b - font::FIRST) as usize];
        if gw > 0 && gh > 0 {
            let cov = &font::COVERAGE[off as usize..(off + len) as usize];
            let gx = penx + left as f32 * scale;
            let gy = y + top as f32 * scale;
            let (dw, dh) = (gw as f32 * scale, gh as f32 * scale);
            let (bx0, by0, bx1, by1) = cv.bbox(gx, gy, gx + dw, gy + dh);
            for py in by0..by1 {
                for px in bx0..bx1 {
                    let u =
                        ((px as f32 + 0.5 - gx) / dw * gw as f32 - 0.5).clamp(0.0, gw as f32 - 1.0);
                    let vv =
                        ((py as f32 + 0.5 - gy) / dh * gh as f32 - 0.5).clamp(0.0, gh as f32 - 1.0);
                    let (x0, y0c) = (u.floor() as usize, vv.floor() as usize);
                    let (x1, y1c) = (
                        (x0 + 1).min(gw as usize - 1),
                        (y0c + 1).min(gh as usize - 1),
                    );
                    let (fx, fy) = (u - x0 as f32, vv - y0c as f32);
                    let sample = |sx: usize, sy: usize| cov[sy * gw as usize + sx] as f32 / 255.0;
                    let c = sample(x0, y0c) * (1.0 - fx) * (1.0 - fy)
                        + sample(x1, y0c) * fx * (1.0 - fy)
                        + sample(x0, y1c) * (1.0 - fx) * fy
                        + sample(x1, y1c) * fx * fy;
                    if c > 0.0 {
                        cv.blend(px, py, rgba, c);
                    }
                }
            }
        }
        penx += advance as f32 * scale;
    }
}

// ---- command-buffer reader --------------------------------------------------

struct Reader<'a> {
    b: &'a [u8],
    i: usize,
}

impl<'a> Reader<'a> {
    fn u8(&mut self) -> Option<u8> {
        let v = *self.b.get(self.i)?;
        self.i += 1;
        Some(v)
    }
    fn u32(&mut self) -> Option<u32> {
        let s = self.b.get(self.i..self.i + 4)?;
        self.i += 4;
        Some(u32::from_le_bytes([s[0], s[1], s[2], s[3]]))
    }
    fn f32(&mut self) -> Option<f32> {
        let s = self.b.get(self.i..self.i + 4)?;
        self.i += 4;
        Some(f32::from_le_bytes([s[0], s[1], s[2], s[3]]))
    }
    fn rgba(&mut self) -> Option<[f32; 4]> {
        let s = self.b.get(self.i..self.i + 4)?;
        self.i += 4;
        Some([
            s[0] as f32 / 255.0,
            s[1] as f32 / 255.0,
            s[2] as f32 / 255.0,
            s[3] as f32 / 255.0,
        ])
    }
    fn pts(&mut self, n: usize) -> Option<Vec<(f32, f32)>> {
        let mut v = Vec::with_capacity(n);
        for _ in 0..n {
            v.push((self.f32()?, self.f32()?));
        }
        Some(v)
    }
    fn bytes(&mut self, n: usize) -> Option<&'a [u8]> {
        let s = self.b.get(self.i..self.i + n)?;
        self.i += n;
        Some(s)
    }
}

/// Parse and paint a display list, retaining the native byte framebuffer so a
/// latency-oriented PNG export can feed it straight into the encoder.
fn rasterize(cmds: &[u8], w: usize, h: usize, opaque_white: bool) -> Option<Canvas> {
    if w == 0 || h == 0 {
        return None;
    }
    let mut cv = Canvas::new(w, h, opaque_white);
    let mut r = Reader { b: cmds, i: 0 };
    while r.i < cmds.len() {
        let op = r.u8()?;
        let ok = (|| -> Option<()> {
            match op {
                OP_CLIP => {
                    let (x, y, cw, ch) = (r.f32()?, r.f32()?, r.f32()?, r.f32()?);
                    cv.clip = [
                        x.max(0.0),
                        y.max(0.0),
                        (x + cw).min(w as f32),
                        (y + ch).min(h as f32),
                    ];
                }
                OP_FILL_POLY => {
                    let n = r.u32()? as usize;
                    let pts = r.pts(n)?;
                    let c = r.rgba()?;
                    if !fill_rect(&mut cv, &pts, c) {
                        fill_poly(&mut cv, &pts, |_, _| c);
                    }
                }
                OP_FILL_POLY_GRAD => {
                    let n = r.u32()? as usize;
                    let pts = r.pts(n)?;
                    let (g0x, g0y, g1x, g1y) = (r.f32()?, r.f32()?, r.f32()?, r.f32()?);
                    let ns = r.u32()? as usize;
                    let mut stops = Vec::with_capacity(ns);
                    for _ in 0..ns {
                        stops.push((r.f32()?, r.rgba()?));
                    }
                    let (dx, dy) = (g1x - g0x, g1y - g0y);
                    let len2 = (dx * dx + dy * dy).max(1e-9);
                    fill_poly(&mut cv, &pts, |x, y| {
                        let t = (((x - g0x) * dx + (y - g0y) * dy) / len2).clamp(0.0, 1.0);
                        grad_color(&stops, t)
                    });
                }
                OP_STROKE => {
                    let n = r.u32()? as usize;
                    let pts = r.pts(n)?;
                    let width = r.f32()?;
                    let c = r.rgba()?;
                    let closed = r.u8()? != 0;
                    let nd = r.u32()? as usize;
                    let mut dash = Vec::with_capacity(nd);
                    for _ in 0..nd {
                        dash.push(r.f32()?);
                    }
                    stroke(&mut cv, &pts, width, c, closed, &dash);
                }
                OP_POINT => {
                    let (cx, cy, rr) = (r.f32()?, r.f32()?, r.f32()?);
                    let sym = r.u8()?;
                    let fill = r.rgba()?;
                    let sw = r.f32()?;
                    let st = r.rgba()?;
                    point(&mut cv, cx, cy, rr, sym, fill, sw, st);
                }
                OP_IMAGE => {
                    let (dx, dy, dw, dh) = (r.f32()?, r.f32()?, r.f32()?, r.f32()?);
                    let (iw, ih) = (r.u32()? as usize, r.u32()? as usize);
                    let nearest = r.u8()? != 0;
                    let src = r.bytes(iw.checked_mul(ih)?.checked_mul(4)?)?;
                    blit(&mut cv, dx, dy, dw, dh, iw, ih, src, nearest);
                }
                OP_TEXT => {
                    let (x, y) = (r.f32()?, r.f32()?);
                    let anchor = r.u8()?;
                    let size = r.f32()?;
                    let c = r.rgba()?;
                    let nb = r.u32()? as usize;
                    let s = r.bytes(nb)?;
                    text(&mut cv, x, y, anchor, size, c, s);
                }
                OP_POINTS => {
                    // Batched marks, struct-of-arrays: one header (symbol +
                    // shared stroke) then cx/cy/r f32 arrays and per-point
                    // RGBA8 fills. Lets Python pack whole NumPy columns in one
                    // shot instead of a per-point OP_POINT loop; each mark
                    // paints exactly like OP_POINT (parity-tested below).
                    let n = r.u32()? as usize;
                    let sym = r.u8()?;
                    let sw = r.f32()?;
                    let st = r.rgba()?;
                    let bytes4 = n.checked_mul(4)?;
                    let xs = r.bytes(bytes4)?;
                    let ys = r.bytes(bytes4)?;
                    let rs = r.bytes(bytes4)?;
                    let fills = r.bytes(bytes4)?;
                    let f32_at = |b: &[u8], i: usize| {
                        f32::from_le_bytes([b[4 * i], b[4 * i + 1], b[4 * i + 2], b[4 * i + 3]])
                    };
                    for i in 0..n {
                        let (cx, cy, rr) = (f32_at(xs, i), f32_at(ys, i), f32_at(rs, i));
                        // NaN coordinates poison the whole framebuffer via
                        // NaN-vs-clip comparisons; skip them (the payload
                        // ships only finite marks, this is a backstop).
                        if !(cx.is_finite() && cy.is_finite() && rr.is_finite()) {
                            continue;
                        }
                        let fill = [
                            fills[4 * i] as f32 / 255.0,
                            fills[4 * i + 1] as f32 / 255.0,
                            fills[4 * i + 2] as f32 / 255.0,
                            fills[4 * i + 3] as f32 / 255.0,
                        ];
                        point(&mut cv, cx, cy, rr, sym, fill, sw, st);
                    }
                }
                OP_SEGMENTS => {
                    let n = r.u32()? as usize;
                    let width = r.f32()?;
                    let bytes4 = n.checked_mul(4)?;
                    let x0 = r.bytes(bytes4)?;
                    let y0 = r.bytes(bytes4)?;
                    let x1 = r.bytes(bytes4)?;
                    let y1 = r.bytes(bytes4)?;
                    let colors = r.bytes(bytes4)?;
                    let f32_at = |b: &[u8], i: usize| {
                        f32::from_le_bytes([b[4 * i], b[4 * i + 1], b[4 * i + 2], b[4 * i + 3]])
                    };
                    for i in 0..n {
                        let a = (f32_at(x0, i), f32_at(y0, i));
                        let b = (f32_at(x1, i), f32_at(y1, i));
                        if !(a.0.is_finite()
                            && a.1.is_finite()
                            && b.0.is_finite()
                            && b.1.is_finite())
                        {
                            continue;
                        }
                        let color = [
                            colors[4 * i] as f32 / 255.0,
                            colors[4 * i + 1] as f32 / 255.0,
                            colors[4 * i + 2] as f32 / 255.0,
                            colors[4 * i + 3] as f32 / 255.0,
                        ];
                        stroke_segment(&mut cv, a, b, width, color);
                    }
                }
                _ => return None,
            }
            Some(())
        })();
        ok?;
    }
    Some(cv)
}

/// Parse and paint the display list into `out` (straight-alpha RGBA8,
/// `w*h*4` bytes). Returns false on a malformed buffer or size mismatch.
pub fn rasterize_into(cmds: &[u8], w: usize, h: usize, out: &mut [u8]) -> bool {
    if out.len() != w.checked_mul(h).and_then(|n| n.checked_mul(4)).unwrap_or(0) {
        return false;
    }
    let Some(cv) = rasterize(cmds, w, h, false) else {
        return false;
    };
    cv.to_rgba8(out);
    true
}

/// Fused low-latency raster + PNG path. `Fast` uses fdeflate's PNG-tuned
/// compressor and the Up filter keeps chart backgrounds and horizontal runs
/// compact without an adaptive-filter pass over every row.
pub fn rasterize_png_into(cmds: &[u8], w: usize, h: usize, out: &mut [u8]) -> Option<usize> {
    let (wu, hu) = (u32::try_from(w).ok()?, u32::try_from(h).ok()?);
    let cv = rasterize(cmds, w, h, true)?;
    let mut cursor = Cursor::new(out);
    {
        let mut encoder = png::Encoder::new(&mut cursor, wu, hu);
        encoder.set_color(if cv.opaque {
            png::ColorType::Rgb
        } else {
            png::ColorType::Rgba
        });
        encoder.set_depth(png::BitDepth::Eight);
        encoder.set_compression(png::Compression::Fast);
        encoder.set_filter(png::Filter::Up);
        let mut writer = encoder.write_header().ok()?;
        writer.write_image_data(&cv.px).ok()?;
        writer.finish().ok()?;
    }
    usize::try_from(cursor.position()).ok()
}

fn grad_color(stops: &[(f32, [f32; 4])], t: f32) -> [f32; 4] {
    if stops.is_empty() {
        return [0.0; 4];
    }
    if t <= stops[0].0 {
        return stops[0].1;
    }
    for i in 1..stops.len() {
        if t <= stops[i].0 {
            let (o0, c0) = stops[i - 1];
            let (o1, c1) = stops[i];
            let f = if o1 > o0 { (t - o0) / (o1 - o0) } else { 0.0 };
            return [
                c0[0] + f * (c1[0] - c0[0]),
                c0[1] + f * (c1[1] - c0[1]),
                c0[2] + f * (c1[2] - c0[2]),
                c0[3] + f * (c1[3] - c0[3]),
            ];
        }
    }
    stops[stops.len() - 1].1
}

#[cfg(test)]
mod tests {
    use super::*;

    fn px(out: &[u8], w: usize, x: usize, y: usize) -> [u8; 4] {
        let o = (y * w + x) * 4;
        [out[o], out[o + 1], out[o + 2], out[o + 3]]
    }

    fn u32le(v: u32) -> [u8; 4] {
        v.to_le_bytes()
    }
    fn f32le(v: f32) -> [u8; 4] {
        v.to_le_bytes()
    }

    #[test]
    fn fill_poly_paints_solid_interior() {
        // A red rectangle [2,2]..[8,8] on a 10x10 canvas.
        let mut cmd = vec![OP_FILL_POLY];
        cmd.extend(u32le(4));
        for (x, y) in [(2.0f32, 2.0f32), (8.0, 2.0), (8.0, 8.0), (2.0, 8.0)] {
            cmd.extend(f32le(x));
            cmd.extend(f32le(y));
        }
        cmd.extend([255, 0, 0, 255]);
        let mut out = vec![0u8; 10 * 10 * 4];
        assert!(rasterize_into(&cmd, 10, 10, &mut out));
        assert_eq!(px(&out, 10, 5, 5), [255, 0, 0, 255]); // interior opaque red
        assert_eq!(px(&out, 10, 0, 0), [0, 0, 0, 0]); // outside transparent
    }

    #[test]
    fn clip_confines_fill() {
        let mut cmd = vec![OP_CLIP];
        cmd.extend(f32le(0.0));
        cmd.extend(f32le(0.0));
        cmd.extend(f32le(5.0));
        cmd.extend(f32le(10.0));
        cmd.push(OP_FILL_POLY);
        cmd.extend(u32le(4));
        for (x, y) in [(0.0f32, 0.0f32), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)] {
            cmd.extend(f32le(x));
            cmd.extend(f32le(y));
        }
        cmd.extend([0, 0, 255, 255]);
        let mut out = vec![0u8; 10 * 10 * 4];
        assert!(rasterize_into(&cmd, 10, 10, &mut out));
        assert_eq!(px(&out, 10, 2, 5), [0, 0, 255, 255]); // inside clip
        assert_eq!(px(&out, 10, 8, 5), [0, 0, 0, 0]); // clipped away
    }

    #[test]
    fn stroke_marks_a_line() {
        let mut cmd = vec![OP_STROKE];
        cmd.extend(u32le(2));
        for (x, y) in [(1.0f32, 5.0f32), (9.0, 5.0)] {
            cmd.extend(f32le(x));
            cmd.extend(f32le(y));
        }
        cmd.extend(f32le(2.0)); // width
        cmd.extend([0, 0, 0, 255]);
        cmd.push(0); // not closed
        cmd.extend(u32le(0)); // no dash
        let mut out = vec![0u8; 10 * 10 * 4];
        assert!(rasterize_into(&cmd, 10, 10, &mut out));
        assert!(px(&out, 10, 5, 5)[3] > 200); // on the line
        assert_eq!(px(&out, 10, 5, 0)[3], 0); // far from it
    }

    #[test]
    fn point_circle_fills_center() {
        let mut cmd = vec![OP_POINT];
        cmd.extend(f32le(5.0));
        cmd.extend(f32le(5.0));
        cmd.extend(f32le(3.0));
        cmd.push(0); // circle
        cmd.extend([0, 128, 0, 255]);
        cmd.extend(f32le(0.0)); // no stroke
        cmd.extend([0, 0, 0, 0]);
        let mut out = vec![0u8; 10 * 10 * 4];
        assert!(rasterize_into(&cmd, 10, 10, &mut out));
        assert_eq!(px(&out, 10, 5, 5), [0, 128, 0, 255]);
        assert_eq!(px(&out, 10, 0, 0), [0, 0, 0, 0]);
    }

    #[test]
    fn text_draws_visible_pixels() {
        let mut cmd = vec![OP_TEXT];
        cmd.extend(f32le(1.0));
        cmd.extend(f32le(30.0));
        cmd.push(0); // anchor start
        cmd.extend(f32le(20.0)); // size
        cmd.extend([0, 0, 0, 255]);
        let s = b"5";
        cmd.extend(u32le(s.len() as u32));
        cmd.extend_from_slice(s);
        let mut out = vec![0u8; 40 * 40 * 4];
        assert!(rasterize_into(&cmd, 40, 40, &mut out));
        let ink: u32 = out.chunks(4).map(|p| (p[3] > 32) as u32).sum();
        assert!(ink > 5, "glyph produced no ink: {ink}");
    }

    #[test]
    fn malformed_buffer_is_rejected_not_panicked() {
        let cmd = vec![OP_FILL_POLY, 9, 9, 9, 9]; // claims a huge point count
        let mut out = vec![0u8; 4 * 4 * 4];
        assert!(!rasterize_into(&cmd, 4, 4, &mut out));
    }

    fn one_point(
        cx: f32,
        cy: f32,
        r: f32,
        sym: u8,
        fill: [u8; 4],
        sw: f32,
        st: [u8; 4],
    ) -> Vec<u8> {
        let mut cmd = vec![OP_POINT];
        cmd.extend(f32le(cx));
        cmd.extend(f32le(cy));
        cmd.extend(f32le(r));
        cmd.push(sym);
        cmd.extend(fill);
        cmd.extend(f32le(sw));
        cmd.extend(st);
        cmd
    }

    #[test]
    fn points_batch_matches_point_loop() {
        // The batched opcode must paint pixel-identically to the same marks
        // issued as individual OP_POINT commands, per symbol and with strokes.
        let marks: [(f32, f32, f32, [u8; 4]); 3] = [
            (5.0, 5.0, 3.0, [200, 40, 40, 255]),
            (14.0, 8.0, 2.5, [40, 200, 40, 128]),
            (9.0, 15.0, 4.0, [40, 40, 200, 255]),
        ];
        for (sym, sw) in [(0u8, 0.0f32), (1, 0.0), (3, 1.0)] {
            let st = [10u8, 10, 10, 255];
            let mut batch = vec![OP_POINTS];
            batch.extend(u32le(marks.len() as u32));
            batch.push(sym);
            batch.extend(f32le(sw));
            batch.extend(st);
            for &(cx, ..) in &marks {
                batch.extend(f32le(cx));
            }
            for &(_, cy, ..) in &marks {
                batch.extend(f32le(cy));
            }
            for &(_, _, r, _) in &marks {
                batch.extend(f32le(r));
            }
            for &(.., fill) in &marks {
                batch.extend(fill);
            }
            let mut singles = Vec::new();
            for &(cx, cy, r, fill) in &marks {
                singles.extend(one_point(cx, cy, r, sym, fill, sw, st));
            }
            let mut got = vec![0u8; 20 * 20 * 4];
            let mut want = vec![0u8; 20 * 20 * 4];
            assert!(rasterize_into(&batch, 20, 20, &mut got));
            assert!(rasterize_into(&singles, 20, 20, &mut want));
            assert_eq!(got, want, "sym={sym} sw={sw}");
        }
    }

    #[test]
    fn points_batch_skips_nonfinite_and_rejects_truncation() {
        // A NaN mark must not poison the framebuffer.
        let mut cmd = vec![OP_POINTS];
        cmd.extend(u32le(2));
        cmd.push(0);
        cmd.extend(f32le(0.0));
        cmd.extend([0, 0, 0, 0]);
        for v in [f32::NAN, 5.0] {
            cmd.extend(f32le(v)); // cx
        }
        for v in [2.0f32, 5.0] {
            cmd.extend(f32le(v)); // cy
        }
        for v in [3.0f32, 3.0] {
            cmd.extend(f32le(v)); // r
        }
        cmd.extend([255, 0, 0, 255]);
        cmd.extend([0, 128, 0, 255]);
        let mut out = vec![0u8; 10 * 10 * 4];
        assert!(rasterize_into(&cmd, 10, 10, &mut out));
        assert_eq!(px(&out, 10, 5, 5), [0, 128, 0, 255]); // finite mark painted
        assert_eq!(px(&out, 10, 9, 9), [0, 0, 0, 0]); // NaN mark skipped

        // A batch that claims more marks than the buffer holds is malformed.
        let mut short = vec![OP_POINTS];
        short.extend(u32le(1000));
        short.push(0);
        short.extend(f32le(0.0));
        short.extend([0, 0, 0, 0]);
        short.extend(f32le(1.0)); // far too few bytes for 1000 marks
        assert!(!rasterize_into(&short, 10, 10, &mut out));
    }
}
