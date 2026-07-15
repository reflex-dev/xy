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
const OP_RECTS: u8 = 9;
const OP_TRIANGLES: u8 = 10;
const OP_SMOOTH_STROKE: u8 = 11;
const OP_DENSITY_IMAGE: u8 = 12;
const OP_HEATMAP_IMAGE: u8 = 13;
const OP_AFFINE_POINTS: u8 = 14;
const OP_AFFINE_CHANNEL_POINTS: u8 = 15;
const OP_STROKED_TRIANGLES: u8 = 16;

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
        let o = (y * self.w + x) * self.channels();
        blend_px(&mut self.px, o, self.opaque, rgba);
    }

    /// Full-height window over the framebuffer. Painting through it is
    /// bit-identical to painting the canvas directly.
    fn surface(&mut self) -> Surface<'_> {
        Surface {
            w: self.w,
            y0: 0,
            y1: self.h,
            channels: self.channels(),
            opaque: self.opaque,
            clip: self.clip,
            px: &mut self.px,
        }
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

/// Source-over into one pixel at byte offset `o` — the single blend
/// implementation shared by the canvas and its row-band surfaces.
#[inline]
fn blend_px(px: &mut [u8], o: usize, opaque: bool, rgba: [u8; 4]) {
    let sa = rgba[3] as u32;
    if sa == 0 {
        return;
    }
    let src = [rgba[0] as u32, rgba[1] as u32, rgba[2] as u32];
    if opaque {
        if sa == 255 {
            px[o] = src[0] as u8;
            px[o + 1] = src[1] as u8;
            px[o + 2] = src[2] as u8;
        } else {
            let inv = 255 - sa;
            for (k, source) in src.iter().enumerate() {
                px[o + k] = ((*source * sa + px[o + k] as u32 * inv + 127) / 255) as u8;
            }
        }
        return;
    }
    if sa == 255 {
        px[o] = src[0] as u8;
        px[o + 1] = src[1] as u8;
        px[o + 2] = src[2] as u8;
        px[o + 3] = 255;
        return;
    }
    let da = px[o + 3] as u32;
    let inv = 255 - sa;
    if da == 255 {
        for (k, source) in src.iter().enumerate() {
            px[o + k] = ((*source * sa + px[o + k] as u32 * inv + 127) / 255) as u8;
        }
        return;
    }
    let out_a_num = sa * 255 + da * inv;
    if out_a_num == 0 {
        return;
    }
    for (k, source) in src.iter().enumerate() {
        let num = *source * sa * 255 + px[o + k] as u32 * da * inv;
        px[o + k] = ((num + out_a_num / 2) / out_a_num) as u8;
    }
    px[o + 3] = ((out_a_num + 127) / 255) as u8;
}

/// A horizontal row band of the framebuffer. The parallel batch painters give
/// each worker one disjoint band, so the image needs no locks; a full-height
/// band (`Canvas::surface`) reproduces plain canvas painting bit-for-bit —
/// same blend math, same clip, same traversal order.
struct Surface<'a> {
    px: &'a mut [u8],
    w: usize,
    y0: usize, // absolute first row covered by `px`
    y1: usize, // absolute exclusive end row
    channels: usize,
    opaque: bool,
    clip: [f32; 4],
}

impl Surface<'_> {
    #[inline]
    fn blend_prepared(&mut self, x: usize, y: usize, rgb: [u8; 3], alpha: f32, cov: f32) {
        self.blend_u8(x, y, [rgb[0], rgb[1], rgb[2], to_u8(alpha * cov)]);
    }

    #[inline]
    fn blend_u8(&mut self, x: usize, y: usize, rgba: [u8; 4]) {
        let o = ((y - self.y0) * self.w + x) * self.channels;
        blend_px(self.px, o, self.opaque, rgba);
    }

    /// Clip∩canvas∩band pixel bbox — `Canvas::bbox` further clamped to the
    /// band's row window (identical to it for a full-height band).
    fn bbox(&self, x0: f32, y0: f32, x1: f32, y1: f32) -> (usize, usize, usize, usize) {
        let cx0 = x0.max(self.clip[0]).max(0.0);
        let cy0 = y0.max(self.clip[1]).max(self.y0 as f32);
        let cx1 = x1.min(self.clip[2]).min(self.w as f32);
        let cy1 = y1.min(self.clip[3]).min(self.y1 as f32);
        if cx1 <= cx0 || cy1 <= cy0 {
            return (0, 0, 0, 0);
        }
        (
            cx0.floor() as usize,
            cy0.floor() as usize,
            (cx1.ceil() as usize).min(self.w),
            (cy1.ceil() as usize).min(self.y1),
        )
    }
}

fn stroke_segment(cv: &mut Canvas, a: (f32, f32), b: (f32, f32), width: f32, rgba: [f32; 4]) {
    stroke_segment_at(&mut cv.surface(), a, b, width, rgba);
}

fn stroke_segment_at(cv: &mut Surface, a: (f32, f32), b: (f32, f32), width: f32, rgba: [f32; 4]) {
    stroke_segment_u8_at(cv, a, b, width, rgba.map(to_u8));
}

fn stroke_segment_u8_at(cv: &mut Surface, a: (f32, f32), b: (f32, f32), width: f32, rgba: [u8; 4]) {
    if width <= 0.0 {
        return;
    }
    let hw = width * 0.5;
    let outer = hw + 0.5;
    let outer2 = outer * outer;
    let inner = (hw - 0.5).max(0.0);
    let inner2 = inner * inner;
    let rgb = [rgba[0], rgba[1], rgba[2]];
    let alpha = rgba[3] as f32 / 255.0;
    let paint = |cv: &mut Surface, x: usize, y: usize, p: (f32, f32)| {
        let distance2 = seg_dist2(p, a, b);
        if distance2 >= outer2 {
            return;
        }
        if distance2 <= inner2 {
            cv.blend_u8(x, y, rgba);
            return;
        }
        cv.blend_prepared(x, y, rgb, alpha, outer - distance2.sqrt());
    };
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
                paint(cv, x, y, (x as f32 + 0.5, y as f32 + 0.5));
            }
        }
    } else if dy.abs() > 1e-6 {
        for y in by0..by1 {
            let t = ((y as f32 + 0.5 - a.1) / dy).clamp(0.0, 1.0);
            let center = a.0 + t * dx;
            let sx0 = ((center - hw - 1.0).floor() as usize).max(bx0);
            let sx1 = ((center + hw + 1.0).ceil() as usize).min(bx1);
            for x in sx0..sx1 {
                paint(cv, x, y, (x as f32 + 0.5, y as f32 + 0.5));
            }
        }
    } else {
        for y in by0..by1 {
            for x in bx0..bx1 {
                paint(cv, x, y, (x as f32 + 0.5, y as f32 + 0.5));
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

type StrokeSegment = ((f32, f32), (f32, f32));

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
    stroke_with_threads(cv, pts, width, rgba, closed, dash, None);
}

fn stroke_with_threads(
    cv: &mut Canvas,
    pts: &[(f32, f32)],
    width: f32,
    rgba: [f32; 4],
    closed: bool,
    dash: &[f32],
    forced_threads: Option<usize>,
) {
    if pts.len() < 2 || width <= 0.0 {
        return;
    }
    if pts.len() == 2 && !closed && dash.is_empty() {
        stroke_segment(cv, pts[0], pts[1], width, rgba);
        return;
    }
    let hw = width * 0.5;
    let mut segs: Vec<StrokeSegment> = Vec::new();
    let n = pts.len();
    let last = if closed { n } else { n - 1 };
    let raw: Vec<StrokeSegment> = (0..last).map(|i| (pts[i], pts[(i + 1) % n])).collect();

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

    // Long polylines are one logical stroke, so OP_SEGMENTS cannot help them:
    // joins must max-combine coverage and composite once. Row bands preserve
    // that invariant because every pixel belongs to exactly one band, while
    // segment indices remain in original order inside each bucket.
    let ext = hw + 1.0;
    let est_px = segs.iter().fold(0.0f32, |work, (a, b)| {
        work + ((a.0 - b.0).abs() + 2.0 * ext) * ((a.1 - b.1).abs() + 2.0 * ext)
    });
    let threads = forced_threads
        .unwrap_or_else(|| raster_fanout(est_px, STROKE_FANOUT_PX, cv.h))
        .max(1);
    if threads > 1 {
        paint_banded(
            cv,
            threads,
            segs.len(),
            |i| {
                let (a, b) = segs[i];
                Some((a.1.min(b.1) - ext, a.1.max(b.1) + ext))
            },
            |surface, indices| stroke_segments_band(surface, &segs, indices, hw, rgba),
        );
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
    // A polyline is normally a few pixels wide but its overall bounding box
    // spans most of the plot. Scanning that entire box to composite a thin
    // stroke makes export cost follow canvas area instead of painted pixels.
    // Record each scratch pixel on its first non-zero coverage and visit only
    // those pixels below. Later overlapping segments still max-combine into
    // the same scratch byte, so joins and output bytes remain identical.
    let mut touched = Vec::<usize>::with_capacity(segs.len().saturating_mul(8));
    for (a, b) in &segs {
        let sx0 = ((a.0.min(b.0) - hw - 1.0).floor() as usize).max(bx0);
        let sy0 = ((a.1.min(b.1) - hw - 1.0).floor() as usize).max(by0);
        let sx1 = ((a.0.max(b.0) + hw + 1.0).ceil() as usize).min(bx1);
        let sy1 = ((a.1.max(b.1) + hw + 1.0).ceil() as usize).min(by1);
        for y in sy0..sy1 {
            for x in sx0..sx1 {
                let c = seg_coverage((x as f32 + 0.5, y as f32 + 0.5), *a, *b, hw);
                if c > 0.0 {
                    let index = (y - by0) * sw + (x - bx0);
                    let s = &mut scratch[index];
                    let coverage = to_u8(c);
                    if *s == 0 {
                        touched.push(index);
                    }
                    if coverage > *s {
                        *s = coverage;
                    }
                }
            }
        }
    }
    for index in touched {
        let c = scratch[index];
        let (row, col) = (index / sw, index % sw);
        cv.blend(bx0 + col, by0 + row, rgba, c as f32 / 255.0);
    }
}

/// Paint one disjoint row band of a logical polyline. Coverage bytes are
/// max-combined exactly like the serial whole-canvas path, then each touched
/// pixel is blended once; splitting only changes ownership, never arithmetic.
fn stroke_segments_band(
    cv: &mut Surface,
    segs: &[StrokeSegment],
    indices: &[u32],
    hw: f32,
    rgba: [f32; 4],
) {
    let mut xmin = f32::INFINITY;
    let mut ymin = f32::INFINITY;
    let mut xmax = f32::NEG_INFINITY;
    let mut ymax = f32::NEG_INFINITY;
    for &index in indices {
        let (a, b) = segs[index as usize];
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
    if bx1 <= bx0 || by1 <= by0 {
        return;
    }
    let (sw, sh) = (bx1 - bx0, by1 - by0);
    let mut scratch = vec![0u8; sw * sh];
    let mut touched = Vec::<usize>::with_capacity(indices.len().saturating_mul(8));
    for &index in indices {
        let (a, b) = segs[index as usize];
        let sx0 = ((a.0.min(b.0) - hw - 1.0).floor() as usize).max(bx0);
        let sy0 = ((a.1.min(b.1) - hw - 1.0).floor() as usize).max(by0);
        let sx1 = ((a.0.max(b.0) + hw + 1.0).ceil() as usize).min(bx1);
        let sy1 = ((a.1.max(b.1) + hw + 1.0).ceil() as usize).min(by1);
        for y in sy0..sy1 {
            for x in sx0..sx1 {
                let raw_coverage = seg_coverage((x as f32 + 0.5, y as f32 + 0.5), a, b, hw);
                if raw_coverage <= 0.0 {
                    continue;
                }
                let coverage = to_u8(raw_coverage);
                let scratch_index = (y - by0) * sw + (x - bx0);
                let slot = &mut scratch[scratch_index];
                if *slot == 0 {
                    touched.push(scratch_index);
                }
                if coverage > *slot {
                    *slot = coverage;
                }
            }
        }
    }
    let rgb = [to_u8(rgba[0]), to_u8(rgba[1]), to_u8(rgba[2])];
    for index in touched {
        let (row, col) = (index / sw, index % sw);
        cv.blend_prepared(
            bx0 + col,
            by0 + row,
            rgb,
            rgba[3],
            scratch[index] as f32 / 255.0,
        );
    }
}

// ---- point / symbol (signed distance field) ---------------------------------

#[inline]
fn segment_distance(p: (f32, f32), a: (f32, f32), b: (f32, f32)) -> f32 {
    let e = (b.0 - a.0, b.1 - a.1);
    let v = (p.0 - a.0, p.1 - a.1);
    let h = ((v.0 * e.0 + v.1 * e.1) / (e.0 * e.0 + e.1 * e.1)).clamp(0.0, 1.0);
    ((v.0 - e.0 * h).powi(2) + (v.1 - e.1 * h).powi(2)).sqrt()
}

#[inline]
fn triangle_sdf(p: (f32, f32), a: (f32, f32), b: (f32, f32), c: (f32, f32)) -> f32 {
    let cross = |u: (f32, f32), v: (f32, f32), q: (f32, f32)| {
        (v.0 - u.0) * (q.1 - u.1) - (v.1 - u.1) * (q.0 - u.0)
    };
    let (c0, c1, c2) = (cross(a, b, p), cross(b, c, p), cross(c, a, p));
    let inside = (c0 >= 0.0 && c1 >= 0.0 && c2 >= 0.0) || (c0 <= 0.0 && c1 <= 0.0 && c2 <= 0.0);
    let d = segment_distance(p, a, b)
        .min(segment_distance(p, b, c))
        .min(segment_distance(p, c, a));
    if inside {
        -d
    } else {
        d
    }
}

#[inline]
fn pentagon_sdf(p: (f32, f32), r: f32) -> f32 {
    // Matplotlib Path.unit_regular_polygon(5), scaled to the marker radius.
    let vertices = [
        (0.0, -r),
        (-0.951_056_54 * r, -0.309_017 * r),
        (-0.587_785_24 * r, 0.809_017 * r),
        (0.587_785_24 * r, 0.809_017 * r),
        (0.951_056_54 * r, -0.309_017 * r),
    ];
    let mut distance = f32::INFINITY;
    let mut has_positive = false;
    let mut has_negative = false;
    for index in 0..5 {
        let a = vertices[index];
        let b = vertices[(index + 1) % 5];
        distance = distance.min(segment_distance(p, a, b));
        let cross = (b.0 - a.0) * (p.1 - a.1) - (b.1 - a.1) * (p.0 - a.0);
        has_positive |= cross > 0.0;
        has_negative |= cross < 0.0;
    }
    if has_positive && has_negative {
        distance
    } else {
        -distance
    }
}

#[inline]
fn symbol_sdf(px: f32, py: f32, r: f32, sym: u8) -> f32 {
    match sym {
        1 => px.abs().max(py.abs()) - r, // square
        2 => (px.abs() + py.abs()) - r,  // diamond
        3 | 8 | 9 | 10 => {
            // Matplotlib's normalized triangle: apex at one edge and a
            // full-width base at the opposite edge.
            let d = match sym {
                8 => (-px, -py), // down
                9 => (py, -px),  // left
                10 => (-py, px), // right
                _ => (px, py),
            };
            triangle_sdf(d, (0.0, -r), (-r, r), (r, r))
        }
        4 => {
            // plus / cross
            let (ax, ay) = (px.abs(), py.abs());
            (ax - 0.34 * r).max(ay - r).min((ax - r).max(ay - 0.34 * r))
        }
        11 => {
            // diagonal cross (matplotlib's x/X), distinct from the plus glyph
            let qx = (px + py) * std::f32::consts::FRAC_1_SQRT_2;
            let qy = (py - px) * std::f32::consts::FRAC_1_SQRT_2;
            let (ax, ay) = (qx.abs(), qy.abs());
            (ax - 0.34 * r).max(ay - r).min((ax - r).max(ay - 0.34 * r))
        }
        13 => px.abs().max(py.abs()) - r,      // snapped pixel
        14 => (px.abs() / 0.6 + py.abs()) - r, // thin diamond
        15 => {
            // Unfilled plus: its width comes from markeredgewidth below.
            let (ax, ay) = (px.abs(), py.abs());
            (ax - r).max(ay).min((ay - r).max(ax))
        }
        16 => {
            // Unfilled x: rotate the same two line segments by 45 degrees.
            let qx = (px + py) * std::f32::consts::FRAC_1_SQRT_2;
            let qy = (py - px) * std::f32::consts::FRAC_1_SQRT_2;
            let (ax, ay) = (qx.abs(), qy.abs());
            (ax - r).max(ay).min((ay - r).max(ax))
        }
        5 => {
            // regular hexagon, pointy top (IQ SDF, x/y swapped for a top vertex)
            let (k0, k1, k2) = (-0.866_025_4_f32, 0.5_f32, 0.577_350_3_f32);
            let mut p = (py.abs(), px.abs());
            let m = (k0 * p.0 + k1 * p.1).min(0.0);
            p = (p.0 - 2.0 * m * k0, p.1 - 2.0 * m * k1);
            p = (p.0 - p.0.clamp(-k2 * r, k2 * r), p.1 - r);
            (p.0 * p.0 + p.1 * p.1).sqrt() * p.1.signum()
        }
        6 => pentagon_sdf((px, py), r),
        7 => {
            // five-pointed star, apex up (IQ SDF)
            let rf = 0.45_f32;
            let (k1x, k1y) = (0.809_017_f32, -0.587_785_25_f32);
            let (k2x, k2y) = (-k1x, k1y);
            let mut p = (px.abs(), -py); // flip y so a point faces up
            let d1 = k1x * p.0 + k1y * p.1;
            let m1 = d1.max(0.0);
            p = (p.0 - 2.0 * m1 * k1x, p.1 - 2.0 * m1 * k1y);
            let d2 = k2x * p.0 + k2y * p.1;
            let m2 = d2.max(0.0);
            p = (p.0 - 2.0 * m2 * k2x, p.1 - 2.0 * m2 * k2y);
            p = (p.0.abs(), p.1 - r);
            let ba = (rf * -k1y - 0.0, rf * k1x - 1.0);
            let h = (p.0 * ba.0 + p.1 * ba.1) / (ba.0 * ba.0 + ba.1 * ba.1);
            let h = h.clamp(0.0, r);
            let q = (p.0 - ba.0 * h, p.1 - ba.1 * h);
            (q.0 * q.0 + q.1 * q.1).sqrt() * (p.1 * ba.0 - p.0 * ba.1).signum()
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
    point_u8(cv, cx, cy, r, sym, fill.map(to_u8), sw, stroke.map(to_u8));
}

#[allow(clippy::too_many_arguments)]
fn point_u8(
    cv: &mut Canvas,
    cx: f32,
    cy: f32,
    r: f32,
    sym: u8,
    fill: [u8; 4],
    sw: f32,
    stroke: [u8; 4],
) {
    point_u8_at(&mut cv.surface(), cx, cy, r, sym, fill, sw, stroke);
}

#[allow(clippy::too_many_arguments)]
fn point_u8_at(
    cv: &mut Surface,
    cx: f32,
    cy: f32,
    r: f32,
    sym: u8,
    fill: [u8; 4],
    sw: f32,
    stroke: [u8; 4],
) {
    // Batched scatter commands already carry RGBA8. Keep those colors in
    // their wire format instead of round-tripping every point through f32.
    let fill_rgb = [fill[0], fill[1], fill[2]];
    let stroke_rgb = [stroke[0], stroke[1], stroke[2]];
    let fill_alpha = fill[3] as f32 / 255.0;
    let stroke_alpha = stroke[3] as f32 / 255.0;
    let ext = r + 1.0;
    let (bx0, by0, bx1, by1) = cv.bbox(cx - ext, cy - ext, cx + ext, cy + ext);
    if sw <= 0.0 && sym == 0 {
        // Stroke-free circle — the default mark and the overwhelming batch
        // case. Classify each pixel by squared distance first: fully outside
        // and fully covered pixels never pay the sqrt or the float coverage
        // math, only the thin AA annulus does. The margins are conservative
        // (well beyond f32 rounding), so any pixel the classification cannot
        // prove lands on the exact SDF path — output is bit-identical to it.
        // For a solid pixel `to_u8((fill[3]/255) * 1.0)` round-trips to
        // exactly `fill[3]`, so the direct integer blend is the same blend.
        let solid2 = {
            let t = r - 0.5;
            if t > 0.0 {
                t * t * (1.0 - 1e-5)
            } else {
                -1.0
            }
        };
        let reject2 = {
            let t = r + 0.5;
            t * t * (1.0 + 1e-5)
        };
        for y in by0..by1 {
            let dy = y as f32 + 0.5 - cy;
            let dy2 = dy * dy;
            for x in bx0..bx1 {
                let dx = x as f32 + 0.5 - cx;
                let q = dx * dx + dy2;
                if q >= reject2 {
                    continue;
                }
                if q <= solid2 {
                    cv.blend_u8(x, y, fill);
                    continue;
                }
                let c = (0.5 - (q.sqrt() - r)).clamp(0.0, 1.0);
                if c > 0.0 {
                    cv.blend_prepared(x, y, fill_rgb, fill_alpha, c);
                }
            }
        }
        return;
    }
    for y in by0..by1 {
        for x in bx0..bx1 {
            let d = symbol_sdf(x as f32 + 0.5 - cx, y as f32 + 0.5 - cy, r, sym);
            if sw > 0.0 {
                let outer = (0.5 - d).clamp(0.0, 1.0);
                let path = (0.5 - (d + sw * 0.5)).clamp(0.0, 1.0);
                let inner = (0.5 - (d + sw)).clamp(0.0, 1.0);
                if path > 0.0 {
                    cv.blend_prepared(x, y, fill_rgb, fill_alpha, path);
                }
                let ring = outer - inner;
                if ring > 0.0 {
                    cv.blend_prepared(x, y, stroke_rgb, stroke_alpha, ring);
                }
            } else {
                let c = (0.5 - d).clamp(0.0, 1.0);
                if c > 0.0 {
                    cv.blend_prepared(x, y, fill_rgb, fill_alpha, c);
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
    let pixels = dw.max(0.0) * dh.max(0.0);
    let threads = raster_fanout(pixels, IMAGE_FANOUT_PX, cv.h);
    blit_with_threads(cv, dx, dy, dw, dh, iw, ih, src, nearest, threads);
}

const IMAGE_FANOUT_PX: f32 = 250_000.0;

/// Give each image worker a disjoint framebuffer row band. Unlike a mark
/// batch, an image writes every destination pixel once, so no bucketing or
/// ordering merge is needed and the parallel result is byte-identical.
fn paint_image_bands(
    cv: &mut Canvas,
    y0: usize,
    y1: usize,
    threads: usize,
    paint: impl Fn(&mut Surface) + Sync,
) {
    if y1 <= y0 {
        return;
    }
    let threads = threads.min(y1 - y0).max(1);
    let band_rows = (y1 - y0).div_ceil(threads);
    let (w, ch, opaque, clip) = (cv.w, cv.channels(), cv.opaque, cv.clip);
    let row_bytes = w * ch;
    let active = &mut cv.px[y0 * row_bytes..y1 * row_bytes];
    std::thread::scope(|scope| {
        for (band_index, band) in active.chunks_mut(band_rows * row_bytes).enumerate() {
            let first = y0 + band_index * band_rows;
            let rows = band.len() / row_bytes;
            let paint = &paint;
            scope.spawn(move || {
                let mut surface = Surface {
                    px: band,
                    w,
                    y0: first,
                    y1: first + rows,
                    channels: ch,
                    opaque,
                    clip,
                };
                paint(&mut surface);
            });
        }
    });
}

#[allow(clippy::too_many_arguments)]
fn blit_with_threads(
    cv: &mut Canvas,
    dx: f32,
    dy: f32,
    dw: f32,
    dh: f32,
    iw: usize,
    ih: usize,
    src: &[u8],
    nearest: bool,
    threads: usize,
) {
    if iw == 0 || ih == 0 || dw <= 0.0 || dh <= 0.0 {
        return;
    }
    let (bx0, by0, bx1, by1) = cv.bbox(dx, dy, dx + dw, dy + dh);
    if nearest {
        let xmap: Vec<usize> = (bx0..bx1)
            .map(|x| (((x as f32 + 0.5 - dx) / dw * iw as f32).floor() as usize).min(iw - 1))
            .collect();
        paint_image_bands(cv, by0, by1, threads, |surface| {
            for y in surface.y0..surface.y1 {
                let sy = (((y as f32 + 0.5 - dy) / dh * ih as f32).floor() as usize).min(ih - 1);
                for (offset, &sx) in xmap.iter().enumerate() {
                    let source = (sy * iw + sx) * 4;
                    let color = [
                        src[source],
                        src[source + 1],
                        src[source + 2],
                        src[source + 3],
                    ];
                    surface.blend_u8(bx0 + offset, y, color);
                }
            }
        });
        return;
    }
    let xmap: Vec<(usize, usize, f32)> = (bx0..bx1)
        .map(|x| {
            let u = ((x as f32 + 0.5 - dx) / dw * iw as f32 - 0.5).clamp(0.0, iw as f32 - 1.0);
            let x0 = u.floor() as usize;
            (x0, (x0 + 1).min(iw - 1), u - x0 as f32)
        })
        .collect();
    let sample = |sx: usize, sy: usize, k: usize| src[(sy * iw + sx) * 4 + k] as f32 / 255.0;
    paint_image_bands(cv, by0, by1, threads, |surface| {
        for y in surface.y0..surface.y1 {
            let v = ((y as f32 + 0.5 - dy) / dh * ih as f32 - 0.5).clamp(0.0, ih as f32 - 1.0);
            let y0 = v.floor() as usize;
            let y1 = (y0 + 1).min(ih - 1);
            let fy = v - y0 as f32;
            for (offset, &(x0, x1, fx)) in xmap.iter().enumerate() {
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
                surface.blend_u8(bx0 + offset, y, c.map(to_u8));
            }
        }
    });
}

/// Bilinearly sample a bottom-row-first log-u8 density grid through its exact
/// 256-entry RGBA lookup table. This is the same result as `density_rgba_into`
/// followed by `blit`, but avoids the 4x expanded image and its copy.
#[allow(clippy::too_many_arguments)]
fn blit_density(
    cv: &mut Canvas,
    dx: f32,
    dy: f32,
    dw: f32,
    dh: f32,
    iw: usize,
    ih: usize,
    encoded: &[u8],
    lut: &[[u8; 4]; 256],
) {
    if iw == 0 || ih == 0 || dw <= 0.0 || dh <= 0.0 {
        return;
    }
    let (bx0, by0, bx1, by1) = cv.bbox(dx, dy, dx + dw, dy + dh);
    let xmap: Vec<(usize, usize, f32)> = (bx0..bx1)
        .map(|x| {
            let u = ((x as f32 + 0.5 - dx) / dw * iw as f32 - 0.5).clamp(0.0, iw as f32 - 1.0);
            let x0 = u.floor() as usize;
            (x0, (x0 + 1).min(iw - 1), u - x0 as f32)
        })
        .collect();
    let sample = |sx: usize, sy: usize, channel: usize| {
        let code = encoded[(ih - 1 - sy) * iw + sx] as usize;
        lut[code][channel] as f32 / 255.0
    };
    let pixels = dw.max(0.0) * dh.max(0.0);
    let threads = raster_fanout(pixels, IMAGE_FANOUT_PX, cv.h);
    paint_image_bands(cv, by0, by1, threads, |surface| {
        for y in surface.y0..surface.y1 {
            let v = ((y as f32 + 0.5 - dy) / dh * ih as f32 - 0.5).clamp(0.0, ih as f32 - 1.0);
            let y0 = v.floor() as usize;
            let y1 = (y0 + 1).min(ih - 1);
            let fy = v - y0 as f32;
            for (offset, &(x0, x1, fx)) in xmap.iter().enumerate() {
                let w00 = (1.0 - fx) * (1.0 - fy);
                let w10 = fx * (1.0 - fy);
                let w01 = (1.0 - fx) * fy;
                let w11 = fx * fy;
                let mut color = [0.0f32; 4];
                for (channel, value) in color.iter_mut().enumerate() {
                    *value = w00 * sample(x0, y0, channel)
                        + w10 * sample(x1, y0, channel)
                        + w01 * sample(x0, y1, channel)
                        + w11 * sample(x1, y1, channel);
                }
                surface.blend_u8(bx0 + offset, y, color.map(to_u8));
            }
        }
    });
}

/// Nearest-sample normalized f32 or canonical f64 heatmap values and color only
/// destination pixels. Canonical values take the exact bulk-normalizer f32
/// rounding path, so raster-only borrowing cannot change output pixels.
#[allow(clippy::too_many_arguments)]
fn blit_heatmap(
    cv: &mut Canvas,
    dx: f32,
    dy: f32,
    dw: f32,
    dh: f32,
    iw: usize,
    ih: usize,
    values: &[u8],
    canonical: bool,
    domain: [f64; 2],
    stops: &[[u8; 3]],
    alpha: u8,
) {
    if iw == 0 || ih == 0 || dw <= 0.0 || dh <= 0.0 || stops.is_empty() {
        return;
    }
    let (bx0, by0, bx1, by1) = cv.bbox(dx, dy, dx + dw, dy + dh);
    let xmap: Vec<usize> = (bx0..bx1)
        .map(|x| (((x as f32 + 0.5 - dx) / dw * iw as f32).floor() as usize).min(iw - 1))
        .collect();
    let pixels = dw.max(0.0) * dh.max(0.0);
    let threads = raster_fanout(pixels, IMAGE_FANOUT_PX, cv.h);
    paint_image_bands(cv, by0, by1, threads, |surface| {
        for y in surface.y0..surface.y1 {
            let sy = (((y as f32 + 0.5 - dy) / dh * ih as f32).floor() as usize).min(ih - 1);
            let source_row = ih - 1 - sy;
            for (offset, &sx) in xmap.iter().enumerate() {
                let index = source_row * iw + sx;
                let value = if canonical {
                    f64::from(crate::kernels::normalize_one_f32(
                        f64_at(values, index),
                        domain[0],
                        domain[1],
                        f32::NAN,
                    ))
                } else {
                    f64::from(f32_at(values, index))
                };
                let color = crate::kernels::heatmap_color(value, stops, alpha);
                surface.blend_u8(bx0 + offset, y, color);
            }
        }
    });
}

// ---- text (baked glyph atlas) -----------------------------------------------

/// Atlas row for a char: the contiguous ASCII block, then the sorted extras.
fn glyph_index(ch: char) -> Option<usize> {
    let code = ch as u32;
    if (font::FIRST as u32..=font::LAST as u32).contains(&code) {
        return Some((code - font::FIRST as u32) as usize);
    }
    let ascii = (font::LAST - font::FIRST + 1) as usize;
    font::EXTRA_CODEPOINTS
        .binary_search(&code)
        .ok()
        .map(|i| ascii + i)
}

/// High bit of the anchor byte requests 90°-CCW text (bottom-up y-axis titles).
pub const TEXT_ROTATED: u8 = 0x80;
/// 0x40 requests 90°-CW text (top-down right-margin titles, mpl rotation=270).
pub const TEXT_ROTATED_CW: u8 = 0x40;

fn text(cv: &mut Canvas, x: f32, y: f32, anchor: u8, size: f32, rgba: [f32; 4], s: &[u8]) {
    let rotated = anchor & TEXT_ROTATED != 0;
    let rotated_cw = anchor & TEXT_ROTATED_CW != 0;
    let anchor = anchor & !(TEXT_ROTATED | TEXT_ROTATED_CW);
    let scale = size / font::BASE_PX as f32;
    let text = String::from_utf8_lossy(s);
    // Total advance for anchoring.
    let mut adv = 0.0f32;
    for ch in text.chars() {
        if let Some(i) = glyph_index(ch) {
            adv += font::GLYPHS[i].0 as f32;
        }
    }
    // The pen walks +x for horizontal text, -y (upward) when rotated CCW,
    // +y (downward) when rotated CW.
    let (mut penx, mut peny) = if rotated_cw {
        (
            x,
            match anchor {
                1 => y - adv * scale * 0.5,
                2 => y - adv * scale,
                _ => y,
            },
        )
    } else if rotated {
        (
            x,
            match anchor {
                1 => y + adv * scale * 0.5,
                2 => y + adv * scale,
                _ => y,
            },
        )
    } else {
        (
            match anchor {
                1 => x - adv * scale * 0.5,
                2 => x - adv * scale,
                _ => x,
            },
            y,
        )
    };
    for ch in text.chars() {
        let Some(i) = glyph_index(ch) else {
            continue;
        };
        let (advance, gw, gh, left, top, off, len) = font::GLYPHS[i];
        if gw > 0 && gh > 0 {
            let cov = &font::COVERAGE[off as usize..(off + len) as usize];
            let sample = |sx: usize, sy: usize| cov[sy * gw as usize + sx] as f32 / 255.0;
            let bilinear = |u: f32, vv: f32| {
                let u = u.clamp(0.0, gw as f32 - 1.0);
                let vv = vv.clamp(0.0, gh as f32 - 1.0);
                let (x0, y0c) = (u.floor() as usize, vv.floor() as usize);
                let (x1, y1c) = ((x0 + 1).min(gw as usize - 1), (y0c + 1).min(gh as usize - 1));
                let (fx, fy) = (u - x0 as f32, vv - y0c as f32);
                sample(x0, y0c) * (1.0 - fx) * (1.0 - fy)
                    + sample(x1, y0c) * fx * (1.0 - fy)
                    + sample(x0, y1c) * (1.0 - fx) * fy
                    + sample(x1, y1c) * fx * fy
            };
            if rotated_cw {
                // CW: glyph +u (right) points down (+y), +v (down) points -x.
                let gx = penx - (top + gh) as f32 * scale;
                let gy = peny + left as f32 * scale;
                let (dw, dh) = (gh as f32 * scale, gw as f32 * scale);
                let (bx0, by0, bx1, by1) = cv.bbox(gx, gy, gx + dw, gy + dh);
                for py in by0..by1 {
                    for px in bx0..bx1 {
                        let u = (py as f32 + 0.5 - gy) / dh * gw as f32 - 0.5;
                        let vv = (gx + dw - (px as f32 + 0.5)) / dw * gh as f32 - 0.5;
                        let c = bilinear(u, vv);
                        if c > 0.0 {
                            cv.blend(px, py, rgba, c);
                        }
                    }
                }
            } else if rotated {
                // CCW: glyph +u (right) points up (-y), +v (down) points +x.
                let gx = penx + top as f32 * scale;
                let gy = peny - (left + gw) as f32 * scale;
                let (dw, dh) = (gh as f32 * scale, gw as f32 * scale);
                let (bx0, by0, bx1, by1) = cv.bbox(gx, gy, gx + dw, gy + dh);
                for py in by0..by1 {
                    for px in bx0..bx1 {
                        let u = (gy + dh - (py as f32 + 0.5)) / dh * gw as f32 - 0.5;
                        let vv = (px as f32 + 0.5 - gx) / dw * gh as f32 - 0.5;
                        let c = bilinear(u, vv);
                        if c > 0.0 {
                            cv.blend(px, py, rgba, c);
                        }
                    }
                }
            } else {
                let gx = penx + left as f32 * scale;
                let gy = y + top as f32 * scale;
                let (dw, dh) = (gw as f32 * scale, gh as f32 * scale);
                let (bx0, by0, bx1, by1) = cv.bbox(gx, gy, gx + dw, gy + dh);
                for py in by0..by1 {
                    for px in bx0..bx1 {
                        let u = (px as f32 + 0.5 - gx) / dw * gw as f32 - 0.5;
                        let vv = (py as f32 + 0.5 - gy) / dh * gh as f32 - 0.5;
                        let c = bilinear(u, vv);
                        if c > 0.0 {
                            cv.blend(px, py, rgba, c);
                        }
                    }
                }
            }
        }
        if rotated_cw {
            peny += advance as f32 * scale;
        } else if rotated {
            peny -= advance as f32 * scale;
        } else {
            penx += advance as f32 * scale;
        }
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
    fn u64(&mut self) -> Option<u64> {
        let s = self.b.get(self.i..self.i + 8)?;
        self.i += 8;
        Some(u64::from_le_bytes([
            s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7],
        ]))
    }
    fn f32(&mut self) -> Option<f32> {
        let s = self.b.get(self.i..self.i + 4)?;
        self.i += 4;
        Some(f32::from_le_bytes([s[0], s[1], s[2], s[3]]))
    }
    fn f64(&mut self) -> Option<f64> {
        let s = self.b.get(self.i..self.i + 8)?;
        self.i += 8;
        Some(f64::from_le_bytes([
            s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7],
        ]))
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

// ---- batched-mark painting (serial or row-band parallel) --------------------

#[inline]
fn f32_at(b: &[u8], i: usize) -> f32 {
    f32::from_le_bytes([b[4 * i], b[4 * i + 1], b[4 * i + 2], b[4 * i + 3]])
}

#[inline]
fn f64_at(b: &[u8], i: usize) -> f64 {
    let base = i * 8;
    f64::from_le_bytes([
        b[base],
        b[base + 1],
        b[base + 2],
        b[base + 3],
        b[base + 4],
        b[base + 5],
        b[base + 6],
        b[base + 7],
    ])
}

fn smooth_points(
    xs: &[u8],
    ys: &[u8],
    n: usize,
    x_scale: [f64; 4],
    y_scale: [f64; 4],
) -> Vec<(f32, f32)> {
    let mut x = Vec::with_capacity(n);
    let mut y = Vec::with_capacity(n);
    for i in 0..n {
        x.push(f64_at(xs, i));
        y.push(f64_at(ys, i));
    }
    let mut d = vec![0.0f64; n - 1];
    for i in 0..n - 1 {
        let dx = x[i + 1] - x[i];
        d[i] = if dx > 0.0 {
            (y[i + 1] - y[i]) / dx
        } else {
            0.0
        };
    }
    let mut m = vec![0.0f64; n];
    m[0] = d[0];
    m[n - 1] = d[n - 2];
    for i in 1..n - 1 {
        m[i] = if d[i - 1] * d[i] <= 0.0 {
            0.0
        } else {
            (d[i - 1] + d[i]) * 0.5
        };
    }
    for i in 0..n - 1 {
        if d[i] == 0.0 {
            m[i] = 0.0;
            m[i + 1] = 0.0;
            continue;
        }
        let (a, b) = (m[i] / d[i], m[i + 1] / d[i]);
        let sum = a * a + b * b;
        if sum > 9.0 {
            let factor = 3.0 / sum.sqrt();
            m[i] = factor * a * d[i];
            m[i + 1] = factor * b * d[i];
        }
    }
    let map = |value: f64, scale: [f64; 4]| -> f32 {
        let span = if scale[1] == scale[0] {
            1.0
        } else {
            scale[1] - scale[0]
        };
        (scale[2] + (value - scale[0]) / span * (scale[3] - scale[2])) as f32
    };
    let mut points = Vec::with_capacity((n - 1) * 16 + 1);
    points.push((map(x[0], x_scale), map(y[0], y_scale)));
    for i in 0..n - 1 {
        let h = x[i + 1] - x[i];
        if h <= 0.0 {
            points.push((map(x[i + 1], x_scale), map(y[i + 1], y_scale)));
            continue;
        }
        let p0 = (x[i], y[i]);
        let p3 = (x[i + 1], y[i + 1]);
        let c1 = (x[i] + h / 3.0, y[i] + m[i] * h / 3.0);
        let c2 = (x[i + 1] - h / 3.0, y[i + 1] - m[i + 1] * h / 3.0);
        for step in 1..16 {
            let t = step as f64 / 16.0;
            let u = 1.0 - t;
            let bx = u.powi(3) * p0.0
                + 3.0 * u.powi(2) * t * c1.0
                + 3.0 * u * t.powi(2) * c2.0
                + t.powi(3) * p3.0;
            let by = u.powi(3) * p0.1
                + 3.0 * u.powi(2) * t * c1.1
                + 3.0 * u * t.powi(2) * c2.1
                + t.powi(3) * p3.1;
            points.push((map(bx, x_scale), map(by, y_scale)));
        }
        points.push((map(p3.0, x_scale), map(p3.1, y_scale)));
    }
    points
}

#[inline]
fn rgba_at(b: &[u8], i: usize) -> [f32; 4] {
    let base = i * 4;
    [
        b[base] as f32 / 255.0,
        b[base + 1] as f32 / 255.0,
        b[base + 2] as f32 / 255.0,
        b[base + 3] as f32 / 255.0,
    ]
}

/// Fan a batched paint across row bands only when the estimated pixel work
/// dwarfs thread spawn cost, and keep every band at least `MIN_BAND_ROWS`
/// tall. Segment batches cross over earlier than points: anti-aliased distance
/// math dominates their compact wire decode, especially for thousands of
/// short contour segments. Output is bit-identical at any fan-out: bands are
/// disjoint and each pixel still receives blends in mark order.
const POINTS_FANOUT_PX: f32 = 2_000_000.0;
const SEGMENTS_FANOUT_PX: f32 = 100_000.0;
const STROKE_FANOUT_PX: f32 = 100_000.0;
const MIN_BAND_ROWS: usize = 64;

fn raster_fanout(est_px: f32, min_px: f32, rows: usize) -> usize {
    if est_px.is_nan() || est_px < min_px {
        return 1;
    }
    // CodSpeed's simulation gate sums instructions across threads, so fan-out
    // can only read as a regression there no matter how much wall-clock it
    // buys. Pin the gate to the serial path it can faithfully measure; the
    // walltime benchmark CI covers the parallel path.
    static CODSPEED: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    if *CODSPEED.get_or_init(|| std::env::var_os("CODSPEED_ENV").is_some()) {
        return 1;
    }
    let cores = std::thread::available_parallelism().map_or(1, |p| p.get().min(12));
    cores.min(rows / MIN_BAND_ROWS).max(1)
}

/// Split the canvas into row bands, bucket item indices by their vertical
/// extent (one decode pass, order-preserving), and let `threads` workers
/// drain the band queue. Several bands per worker keep dense regions —
/// where real data concentrates ink — from serializing on one thread.
/// Bit-identity at any fan-out: bands are disjoint row ranges, buckets keep
/// item order, so every pixel receives the same blends in the same order as
/// the serial pass.
fn paint_banded(
    cv: &mut Canvas,
    threads: usize,
    n_items: usize,
    y_extent: impl Fn(usize) -> Option<(f32, f32)>,
    paint: impl Fn(&mut Surface, &[u32]) + Sync,
) {
    let (w, h, ch, opaque, clip) = (cv.w, cv.h, cv.channels(), cv.opaque, cv.clip);
    let n_bands = (threads * 4).min(h.div_ceil(8)).max(1);
    let band_rows = h.div_ceil(n_bands);
    let n_bands = h.div_ceil(band_rows);
    let mut buckets = vec![Vec::<u32>::new(); n_bands];
    for i in 0..n_items {
        if let Some((ylo, yhi)) = y_extent(i) {
            if !(ylo.is_finite() && yhi.is_finite()) || yhi < 0.0 || ylo >= h as f32 {
                continue;
            }
            let b0 = ylo.max(0.0) as usize / band_rows;
            let b1 = (yhi.min(h as f32 - 1.0).max(0.0) as usize / band_rows).min(n_bands - 1);
            for bucket in buckets.iter_mut().take(b1 + 1).skip(b0) {
                bucket.push(i as u32);
            }
        }
    }
    let mut jobs = Vec::with_capacity(n_bands);
    let mut rest = cv.px.as_mut_slice();
    let mut y0 = 0;
    for bucket in buckets {
        let take = band_rows.min(h - y0);
        let (band, tail) = rest.split_at_mut(take * w * ch);
        rest = tail;
        if !bucket.is_empty() {
            jobs.push((y0, take, band, bucket));
        }
        y0 += take;
    }
    let queue = std::sync::Mutex::new(jobs.into_iter());
    std::thread::scope(|s| {
        for _ in 0..threads {
            s.spawn(|| loop {
                let job = queue.lock().map(|mut q| q.next()).unwrap_or(None);
                let Some((y0, take, band, bucket)) = job else {
                    break;
                };
                let mut sf = Surface {
                    px: band,
                    w,
                    y0,
                    y1: y0 + take,
                    channels: ch,
                    opaque,
                    clip,
                };
                paint(&mut sf, &bucket);
            });
        }
    });
}

/// One OP_POINTS batch: struct-of-arrays borrowed straight from the wire.
#[inline]
fn resolved_point_stroke(fill: [u8; 4], stroke: [u8; 4]) -> [u8; 4] {
    // A transparent wire stroke is the internal edgecolors="face" marker.
    // Resolve it after channel colors so every point gets its own RGBA edge.
    if stroke[3] == 0 { fill } else { stroke }
}

struct PointsBatch<'a> {
    n: usize,
    sym: u8,
    sw: f32,
    stroke: [u8; 4],
    xs: &'a [u8],
    ys: &'a [u8],
    rs: &'a [u8],
    fills: &'a [u8],
}

fn paint_points(cv: &mut Canvas, batch: &PointsBatch, threads: usize) {
    if threads <= 1 {
        let indices: Vec<u32> = (0..batch.n as u32).collect();
        paint_points_band(&mut cv.surface(), batch, &indices);
        return;
    }
    paint_banded(
        cv,
        threads,
        batch.n,
        |i| {
            let (cy, rr) = (f32_at(batch.ys, i), f32_at(batch.rs, i));
            let ext = rr + batch.sw + 1.0;
            Some((cy - ext, cy + ext))
        },
        |sf, indices| paint_points_band(sf, batch, indices),
    );
}

fn paint_points_band(sf: &mut Surface, b: &PointsBatch, indices: &[u32]) {
    for &i in indices {
        let i = i as usize;
        let (cx, cy, rr) = (f32_at(b.xs, i), f32_at(b.ys, i), f32_at(b.rs, i));
        // NaN coordinates poison the whole framebuffer via NaN-vs-clip
        // comparisons; skip them (the payload ships only finite marks, this
        // is a backstop).
        if !(cx.is_finite() && cy.is_finite() && rr.is_finite()) {
            continue;
        }
        let fill = [
            b.fills[4 * i],
            b.fills[4 * i + 1],
            b.fills[4 * i + 2],
            b.fills[4 * i + 3],
        ];
        point_u8_at(
            sf,
            cx,
            cy,
            rr,
            b.sym,
            fill,
            b.sw,
            resolved_point_stroke(fill, b.stroke),
        );
    }
}

/// One zero-copy axis of OP_AFFINE_POINTS. Values stay in their payload's
/// offset-encoded f32 representation until a mark is actually visited. The
/// operation order mirrors Python's `_column` -> `_Scale` -> `_Cmd.points`
/// path so switching commands cannot move a mark by an f32 rounding unit.
struct AffineAxis<'a> {
    values: &'a [u8],
    decode_scale: f64,
    decode_offset: f64,
    map: [f64; 4], // domain lo/hi, logical px0/px1
    output_scale: f64,
}

impl AffineAxis<'_> {
    #[inline]
    fn project(&self, i: usize) -> f32 {
        let value = f64::from(f32_at(self.values, i)) / self.decode_scale + self.decode_offset;
        let span = self.map[1] - self.map[0];
        let span = if span == 0.0 { 1.0 } else { span };
        let logical = self.map[2] + (value - self.map[0]) / span * (self.map[3] - self.map[2]);
        (logical * self.output_scale) as f32
    }
}

/// Constant-style points whose encoded x/y columns are borrowed from payload
/// spans. This avoids decoded f64, radius, and RGBA arrays while retaining the
/// exact same point painter and row-band parallelism.
struct AffinePointsBatch<'a> {
    n: usize,
    sym: u8,
    sw: f32,
    stroke: [u8; 4],
    radius: f32,
    fill: [u8; 4],
    x: AffineAxis<'a>,
    y: AffineAxis<'a>,
}

fn paint_affine_points(cv: &mut Canvas, batch: &AffinePointsBatch, threads: usize) {
    if threads <= 1 {
        for i in 0..batch.n {
            paint_affine_point(&mut cv.surface(), batch, i);
        }
        return;
    }
    // Row-band painting reads y once while bucketing and again in every band
    // a mark overlaps. Project a compact f32 x/y scratch once for parallel
    // batches; this is 8 bytes/mark versus the old Python path's decoded f64,
    // projected f64/f32, radius, fill, and copied command arrays. Small serial
    // batches remain allocation-free above.
    let mut xs = Vec::with_capacity(batch.n);
    let mut ys = Vec::with_capacity(batch.n);
    for i in 0..batch.n {
        xs.push(batch.x.project(i));
        ys.push(batch.y.project(i));
    }
    let ext = batch.radius + batch.sw + 1.0;
    paint_banded(
        cv,
        threads,
        batch.n,
        |i| {
            let cy = ys[i];
            Some((cy - ext, cy + ext))
        },
        |sf, indices| {
            for &i in indices {
                let i = i as usize;
                let (cx, cy) = (xs[i], ys[i]);
                if cx.is_finite() && cy.is_finite() {
                    point_u8_at(
                        sf,
                        cx,
                        cy,
                        batch.radius,
                        batch.sym,
                        batch.fill,
                        batch.sw,
                        resolved_point_stroke(batch.fill, batch.stroke),
                    );
                }
            }
        },
    );
}

#[inline]
fn paint_affine_point(sf: &mut Surface, batch: &AffinePointsBatch, i: usize) {
    let (cx, cy) = (batch.x.project(i), batch.y.project(i));
    if !(cx.is_finite() && cy.is_finite()) {
        return;
    }
    point_u8_at(
        sf,
        cx,
        cy,
        batch.radius,
        batch.sym,
        batch.fill,
        batch.sw,
        resolved_point_stroke(batch.fill, batch.stroke),
    );
}

/// Screen-space scratch for borrowed affine points with data-driven styling.
/// Python ships only encoded source columns and small LUTs; Rust resolves each
/// radius/color once, then the existing point painter consumes compact arrays.
struct StyledPointsBatch<'a> {
    n: usize,
    sym: u8,
    sw: f32,
    stroke: [u8; 4],
    xs: &'a [f32],
    ys: &'a [f32],
    rs: &'a [f32],
    fills: &'a [[u8; 4]],
}

fn paint_styled_points(cv: &mut Canvas, batch: &StyledPointsBatch, threads: usize) {
    if threads <= 1 {
        for i in 0..batch.n {
            paint_styled_point(&mut cv.surface(), batch, i);
        }
        return;
    }
    paint_banded(
        cv,
        threads,
        batch.n,
        |i| {
            let ext = batch.rs[i] + batch.sw + 1.0;
            Some((batch.ys[i] - ext, batch.ys[i] + ext))
        },
        |surface, indices| {
            for &i in indices {
                paint_styled_point(surface, batch, i as usize);
            }
        },
    );
}

#[inline]
fn paint_styled_point(sf: &mut Surface, batch: &StyledPointsBatch, i: usize) {
    let (cx, cy, radius) = (batch.xs[i], batch.ys[i], batch.rs[i]);
    if !(cx.is_finite() && cy.is_finite() && radius.is_finite()) {
        return;
    }
    point_u8_at(
        sf,
        cx,
        cy,
        radius,
        batch.sym,
        batch.fills[i],
        batch.sw,
        resolved_point_stroke(batch.fills[i], batch.stroke),
    );
}

/// One OP_SEGMENTS batch: struct-of-arrays borrowed straight from the wire.
struct SegmentsBatch<'a> {
    n: usize,
    width: f32,
    x0s: &'a [u8],
    y0s: &'a [u8],
    x1s: &'a [u8],
    y1s: &'a [u8],
    colors: &'a [u8],
}

fn paint_segments(cv: &mut Canvas, batch: &SegmentsBatch, threads: usize) {
    if threads <= 1 {
        let indices: Vec<u32> = (0..batch.n as u32).collect();
        paint_segments_band(&mut cv.surface(), batch, &indices);
        return;
    }
    paint_banded(
        cv,
        threads,
        batch.n,
        |i| {
            let (ay, by) = (f32_at(batch.y0s, i), f32_at(batch.y1s, i));
            let ext = batch.width * 0.5 + 1.0;
            Some((ay.min(by) - ext, ay.max(by) + ext))
        },
        |sf, indices| paint_segments_band(sf, batch, indices),
    );
}

fn paint_segments_band(sf: &mut Surface, sb: &SegmentsBatch, indices: &[u32]) {
    for &i in indices {
        let i = i as usize;
        let a = (f32_at(sb.x0s, i), f32_at(sb.y0s, i));
        let b = (f32_at(sb.x1s, i), f32_at(sb.y1s, i));
        if !(a.0.is_finite() && a.1.is_finite() && b.0.is_finite() && b.1.is_finite()) {
            continue;
        }
        let color = [
            sb.colors[4 * i],
            sb.colors[4 * i + 1],
            sb.colors[4 * i + 2],
            sb.colors[4 * i + 3],
        ];
        stroke_segment_u8_at(sf, a, b, sb.width, color);
    }
}

fn read_span<'a>(reader: &mut Reader<'_>, spans: &[&'a [u8]], byte_len: usize) -> Option<&'a [u8]> {
    let span = reader.u32()? as usize;
    let offset = usize::try_from(reader.u64()?).ok()?;
    let arena = *spans.get(span)?;
    arena.get(offset..offset.checked_add(byte_len)?)
}

fn read_affine_axis<'a>(
    reader: &mut Reader<'_>,
    spans: &[&'a [u8]],
    byte_len: usize,
) -> Option<(&'a [u8], f64, f64)> {
    let values = read_span(reader, spans, byte_len)?;
    let decode_scale = reader.f64()?;
    let decode_offset = reader.f64()?;
    Some((values, decode_scale, decode_offset))
}

/// Parse and paint a display list, retaining the native byte framebuffer so a
/// latency-oriented PNG export can feed it straight into the encoder.
fn rasterize_with_spans(
    cmds: &[u8],
    spans: &[&[u8]],
    w: usize,
    h: usize,
    opaque_white: bool,
) -> Option<Canvas> {
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
                OP_DENSITY_IMAGE => {
                    let (dx, dy, dw, dh) = (r.f32()?, r.f32()?, r.f32()?, r.f32()?);
                    let (iw, ih) = (r.u32()? as usize, r.u32()? as usize);
                    let span = r.u32()? as usize;
                    let byte_offset = usize::try_from(r.u64()?).ok()?;
                    let (maximum, opacity) = (r.f64()?, r.f64()?);
                    let stop_count = r.u32()? as usize;
                    let stop_bytes = r.bytes(stop_count.checked_mul(3)?)?;
                    let stops: Vec<[u8; 3]> = stop_bytes
                        .chunks_exact(3)
                        .map(|stop| [stop[0], stop[1], stop[2]])
                        .collect();
                    let encoded_len = iw.checked_mul(ih)?;
                    let arena = *spans.get(span)?;
                    let encoded = arena.get(byte_offset..byte_offset.checked_add(encoded_len)?)?;
                    let lut = crate::kernels::density_rgba_lut(maximum, &stops, opacity)?;
                    blit_density(&mut cv, dx, dy, dw, dh, iw, ih, encoded, &lut);
                }
                OP_HEATMAP_IMAGE => {
                    let (dx, dy, dw, dh) = (r.f32()?, r.f32()?, r.f32()?, r.f32()?);
                    let (iw, ih) = (r.u32()? as usize, r.u32()? as usize);
                    let span = r.u32()? as usize;
                    let byte_offset = usize::try_from(r.u64()?).ok()?;
                    let encoding = r.u8()?;
                    if encoding > 1 {
                        return None;
                    }
                    let domain = [r.f64()?, r.f64()?];
                    if encoding == 1
                        && !(domain[0].is_finite()
                            && domain[1].is_finite()
                            && domain[1] > domain[0])
                    {
                        return None;
                    }
                    let alpha = r.u8()?;
                    let stop_count = r.u32()? as usize;
                    if stop_count == 0 {
                        return None;
                    }
                    let stop_bytes = r.bytes(stop_count.checked_mul(3)?)?;
                    let stops: Vec<[u8; 3]> = stop_bytes
                        .chunks_exact(3)
                        .map(|stop| [stop[0], stop[1], stop[2]])
                        .collect();
                    let width = if encoding == 1 { 8 } else { 4 };
                    let value_bytes = iw.checked_mul(ih)?.checked_mul(width)?;
                    let arena = *spans.get(span)?;
                    let values = arena.get(byte_offset..byte_offset.checked_add(value_bytes)?)?;
                    blit_heatmap(
                        &mut cv,
                        dx,
                        dy,
                        dw,
                        dh,
                        iw,
                        ih,
                        values,
                        encoding == 1,
                        domain,
                        &stops,
                        alpha,
                    );
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
                    let batch = PointsBatch {
                        n,
                        sym,
                        sw,
                        stroke: st.map(to_u8),
                        xs,
                        ys,
                        rs,
                        fills,
                    };
                    let mut est_px = 0.0f32;
                    for i in 0..n {
                        let rr = f32_at(rs, i);
                        if rr.is_finite() {
                            let side = 2.0 * (rr + sw + 1.0);
                            est_px += side * side;
                        }
                    }
                    paint_points(&mut cv, &batch, raster_fanout(est_px, POINTS_FANOUT_PX, h));
                }
                OP_AFFINE_POINTS => {
                    // Borrow offset-encoded x/y payload columns and fuse their
                    // f64 decode + affine projection into native point paint.
                    let n = r.u32()? as usize;
                    let sym = r.u8()?;
                    let sw = r.f32()?;
                    let stroke = r.rgba()?.map(to_u8);
                    let radius = r.f32()?;
                    let fill = r.rgba()?.map(to_u8);
                    if !(sw.is_finite() && radius.is_finite() && sw >= 0.0 && radius >= 0.0) {
                        return None;
                    }
                    let bytes4 = n.checked_mul(4)?;
                    let (xs, x_decode_scale, x_decode_offset) =
                        read_affine_axis(&mut r, spans, bytes4)?;
                    let (ys, y_decode_scale, y_decode_offset) =
                        read_affine_axis(&mut r, spans, bytes4)?;
                    let x_map = [r.f64()?, r.f64()?, r.f64()?, r.f64()?];
                    let y_map = [r.f64()?, r.f64()?, r.f64()?, r.f64()?];
                    let output_scale = r.f64()?;
                    if !x_decode_scale.is_finite()
                        || x_decode_scale == 0.0
                        || !x_decode_offset.is_finite()
                        || !y_decode_scale.is_finite()
                        || y_decode_scale == 0.0
                        || !y_decode_offset.is_finite()
                        || !x_map.into_iter().all(f64::is_finite)
                        || !y_map.into_iter().all(f64::is_finite)
                        || !output_scale.is_finite()
                    {
                        return None;
                    }
                    let batch = AffinePointsBatch {
                        n,
                        sym,
                        sw,
                        stroke,
                        radius,
                        fill,
                        x: AffineAxis {
                            values: xs,
                            decode_scale: x_decode_scale,
                            decode_offset: x_decode_offset,
                            map: x_map,
                            output_scale,
                        },
                        y: AffineAxis {
                            values: ys,
                            decode_scale: y_decode_scale,
                            decode_offset: y_decode_offset,
                            map: y_map,
                            output_scale,
                        },
                    };
                    let side = 2.0 * (radius + sw + 1.0);
                    let est_px = side * side * n as f32;
                    paint_affine_points(
                        &mut cv,
                        &batch,
                        raster_fanout(est_px, POINTS_FANOUT_PX, h),
                    );
                }
                OP_AFFINE_CHANNEL_POINTS => {
                    let n = r.u32()? as usize;
                    let sym = r.u8()?;
                    let sw = r.f32()?;
                    let stroke = r.rgba()?.map(to_u8);
                    if !(sw.is_finite() && sw >= 0.0) {
                        return None;
                    }
                    let bytes4 = n.checked_mul(4)?;
                    let (x_values, x_decode_scale, x_decode_offset) =
                        read_affine_axis(&mut r, spans, bytes4)?;
                    let (y_values, y_decode_scale, y_decode_offset) =
                        read_affine_axis(&mut r, spans, bytes4)?;
                    let x_map = [r.f64()?, r.f64()?, r.f64()?, r.f64()?];
                    let y_map = [r.f64()?, r.f64()?, r.f64()?, r.f64()?];
                    let output_scale = r.f64()?;
                    if !x_decode_scale.is_finite()
                        || x_decode_scale == 0.0
                        || !x_decode_offset.is_finite()
                        || !y_decode_scale.is_finite()
                        || y_decode_scale == 0.0
                        || !y_decode_offset.is_finite()
                        || !x_map.into_iter().all(f64::is_finite)
                        || !y_map.into_iter().all(f64::is_finite)
                        || !output_scale.is_finite()
                        || output_scale <= 0.0
                    {
                        return None;
                    }
                    let x_axis = AffineAxis {
                        values: x_values,
                        decode_scale: x_decode_scale,
                        decode_offset: x_decode_offset,
                        map: x_map,
                        output_scale,
                    };
                    let y_axis = AffineAxis {
                        values: y_values,
                        decode_scale: y_decode_scale,
                        decode_offset: y_decode_offset,
                        map: y_map,
                        output_scale,
                    };

                    let color_mode = r.u8()?;
                    if color_mode > 2 {
                        return None;
                    }
                    let constant_fill = r.rgba()?.map(to_u8);
                    let mut color_values = &[][..];
                    let mut color_encoding = 0u8;
                    let mut palette = Vec::<[u8; 3]>::new();
                    if color_mode != 0 {
                        color_encoding = r.u8()?;
                        if color_encoding > 1 || (color_mode == 1 && color_encoding != 0) {
                            return None;
                        }
                        let color_bytes = if color_encoding == 1 { n } else { bytes4 };
                        color_values = read_span(&mut r, spans, color_bytes)?;
                        let count = r.u32()? as usize;
                        if count == 0 {
                            return None;
                        }
                        let bytes = r.bytes(count.checked_mul(3)?)?;
                        palette = bytes
                            .chunks_exact(3)
                            .map(|entry| [entry[0], entry[1], entry[2]])
                            .collect();
                    }

                    let size_mode = r.u8()?;
                    if size_mode > 1 {
                        return None;
                    }
                    let mut size_values = &[][..];
                    let mut constant_radius = 0.0f32;
                    let mut size_range = [0.0f64; 2];
                    if size_mode == 1 {
                        size_values = read_span(&mut r, spans, bytes4)?;
                        size_range = [r.f64()?, r.f64()?];
                        if !size_range.into_iter().all(f64::is_finite)
                            || size_range[0] < 0.0
                            || size_range[1] < 0.0
                        {
                            return None;
                        }
                    } else {
                        constant_radius = r.f32()?;
                        if !(constant_radius.is_finite() && constant_radius >= 0.0) {
                            return None;
                        }
                    }

                    let mut xs = Vec::with_capacity(n);
                    let mut ys = Vec::with_capacity(n);
                    let mut radii = Vec::with_capacity(n);
                    let mut fills = Vec::with_capacity(n);
                    let mut est_px = 0.0f32;
                    for i in 0..n {
                        xs.push(x_axis.project(i));
                        ys.push(y_axis.project(i));
                        let radius = if size_mode == 1 {
                            let value = f64::from(f32_at(size_values, i)).clamp(0.0, 1.0);
                            (((size_range[0] + (size_range[1] - size_range[0]) * value) / 2.0)
                                * output_scale) as f32
                        } else {
                            constant_radius
                        };
                        radii.push(radius);
                        let fill = match color_mode {
                            1 => crate::kernels::colormap_color(
                                f64::from(f32_at(color_values, i)),
                                &palette,
                                constant_fill[3],
                            ),
                            2 => {
                                let index = if color_encoding == 1 {
                                    usize::from(color_values[i]) % palette.len()
                                } else {
                                    let code = f32_at(color_values, i);
                                    if code.is_finite() {
                                        (code as i64).rem_euclid(palette.len() as i64) as usize
                                    } else {
                                        0
                                    }
                                };
                                let rgb = palette[index];
                                [rgb[0], rgb[1], rgb[2], constant_fill[3]]
                            }
                            _ => constant_fill,
                        };
                        fills.push(fill);
                        if radius.is_finite() {
                            let side = 2.0 * (radius + sw + 1.0);
                            est_px += side * side;
                        }
                    }
                    let batch = StyledPointsBatch {
                        n,
                        sym,
                        sw,
                        stroke,
                        xs: &xs,
                        ys: &ys,
                        rs: &radii,
                        fills: &fills,
                    };
                    paint_styled_points(
                        &mut cv,
                        &batch,
                        raster_fanout(est_px, POINTS_FANOUT_PX, h),
                    );
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
                    let batch = SegmentsBatch {
                        n,
                        width,
                        x0s: x0,
                        y0s: y0,
                        x1s: x1,
                        y1s: y1,
                        colors,
                    };
                    let mut est_px = 0.0f32;
                    for i in 0..n {
                        let (dx, dy) =
                            (f32_at(x1, i) - f32_at(x0, i), f32_at(y1, i) - f32_at(y0, i));
                        if dx.is_finite() && dy.is_finite() {
                            est_px += (dx.abs().max(dy.abs()) + 2.0) * (width + 3.0);
                        }
                    }
                    paint_segments(
                        &mut cv,
                        &batch,
                        raster_fanout(est_px, SEGMENTS_FANOUT_PX, h),
                    );
                }
                OP_RECTS => {
                    let n = r.u32()? as usize;
                    let bytes4 = n.checked_mul(4)?;
                    let x0 = r.bytes(bytes4)?;
                    let y0 = r.bytes(bytes4)?;
                    let x1 = r.bytes(bytes4)?;
                    let y1 = r.bytes(bytes4)?;
                    let fills = r.bytes(bytes4)?;
                    for i in 0..n {
                        let (xa, ya, xb, yb) =
                            (f32_at(x0, i), f32_at(y0, i), f32_at(x1, i), f32_at(y1, i));
                        if !(xa.is_finite() && ya.is_finite() && xb.is_finite() && yb.is_finite()) {
                            continue;
                        }
                        let pts = [(xa, ya), (xb, ya), (xb, yb), (xa, yb)];
                        fill_rect(&mut cv, &pts, rgba_at(fills, i));
                    }
                }
                OP_TRIANGLES | OP_STROKED_TRIANGLES => {
                    let n = r.u32()? as usize;
                    let (stroke_width, stroke_color) = if op == OP_STROKED_TRIANGLES {
                        let width = r.f32()?;
                        let color = r.rgba()?;
                        if !(width.is_finite() && width > 0.0) {
                            return None;
                        }
                        (width, color)
                    } else {
                        (0.0, [0.0; 4])
                    };
                    let bytes4 = n.checked_mul(4)?;
                    let x0 = r.bytes(bytes4)?;
                    let y0 = r.bytes(bytes4)?;
                    let x1 = r.bytes(bytes4)?;
                    let y1 = r.bytes(bytes4)?;
                    let x2 = r.bytes(bytes4)?;
                    let y2 = r.bytes(bytes4)?;
                    let fills = r.bytes(bytes4)?;
                    for i in 0..n {
                        let pts = [
                            (f32_at(x0, i), f32_at(y0, i)),
                            (f32_at(x1, i), f32_at(y1, i)),
                            (f32_at(x2, i), f32_at(y2, i)),
                        ];
                        if op == OP_TRIANGLES
                            && !pts.iter().all(|&(x, y)| x.is_finite() && y.is_finite())
                        {
                            continue;
                        }
                        let color = rgba_at(fills, i);
                        fill_poly(&mut cv, &pts, |_, _| color);
                        if stroke_width > 0.0 {
                            stroke(&mut cv, &pts, stroke_width, stroke_color, true, &[]);
                        }
                    }
                }
                OP_SMOOTH_STROKE => {
                    let n = r.u32()? as usize;
                    if n < 2 {
                        return None;
                    }
                    let x_scale = [r.f64()?, r.f64()?, r.f64()?, r.f64()?];
                    let y_scale = [r.f64()?, r.f64()?, r.f64()?, r.f64()?];
                    let bytes8 = n.checked_mul(8)?;
                    let xs = r.bytes(bytes8)?;
                    let ys = r.bytes(bytes8)?;
                    let width = r.f32()?;
                    let color = r.rgba()?;
                    let nd = r.u32()? as usize;
                    let mut dash = Vec::with_capacity(nd);
                    for _ in 0..nd {
                        dash.push(r.f32()?);
                    }
                    let points = smooth_points(xs, ys, n, x_scale, y_scale);
                    stroke(&mut cv, &points, width, color, false, &dash);
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
    rasterize_spans_into(cmds, &[], w, h, out)
}

/// Parse and paint a display list whose commands may reference `data` for the
/// duration of this synchronous call.
pub fn rasterize_data_into(cmds: &[u8], data: &[u8], w: usize, h: usize, out: &mut [u8]) -> bool {
    rasterize_spans_into(cmds, &[data], w, h, out)
}

/// Parse and paint a display list backed by multiple synchronous arenas.
pub fn rasterize_spans_into(
    cmds: &[u8],
    spans: &[&[u8]],
    w: usize,
    h: usize,
    out: &mut [u8],
) -> bool {
    if out.len() != w.checked_mul(h).and_then(|n| n.checked_mul(4)).unwrap_or(0) {
        return false;
    }
    let Some(cv) = rasterize_with_spans(cmds, spans, w, h, false) else {
        return false;
    };
    cv.to_rgba8(out);
    true
}

/// Fused low-latency raster + PNG path. `Fast` uses fdeflate's PNG-tuned
/// compressor and the Up filter keeps chart backgrounds and horizontal runs
/// compact without an adaptive-filter pass over every row.
pub fn rasterize_png_into(cmds: &[u8], w: usize, h: usize, out: &mut [u8]) -> Option<usize> {
    rasterize_png_spans_into(cmds, &[], w, h, out)
}

/// Fused PNG path with a synchronous external display-list data arena.
pub fn rasterize_png_data_into(
    cmds: &[u8],
    data: &[u8],
    w: usize,
    h: usize,
    out: &mut [u8],
) -> Option<usize> {
    rasterize_png_spans_into(cmds, &[data], w, h, out)
}

/// Fused PNG path backed by multiple synchronous display-list arenas.
pub fn rasterize_png_spans_into(
    cmds: &[u8],
    spans: &[&[u8]],
    w: usize,
    h: usize,
    out: &mut [u8],
) -> Option<usize> {
    let (wu, hu) = (u32::try_from(w).ok()?, u32::try_from(h).ok()?);
    let cv = rasterize_with_spans(cmds, spans, w, h, true)?;
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
    fn f64le(v: f64) -> [u8; 8] {
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
    fn prepared_segment_path_matches_float_coverage_reference() {
        let cases = [
            ((-2.0, 6.25), (31.0, 6.25), 0.5, [17, 93, 211, 91]),
            ((8.5, -3.0), (8.5, 24.0), 1.5, [230, 20, 70, 255]),
            ((1.25, 2.75), (27.5, 19.25), 3.0, [40, 180, 90, 173]),
            ((15.25, 9.75), (15.25, 9.75), 2.0, [90, 40, 200, 128]),
        ];
        for opaque in [false, true] {
            let mut fast = Canvas::new(30, 22, opaque);
            fast.clip = [2.0, 1.0, 28.0, 21.0];
            let mut reference = Canvas::new(30, 22, opaque);
            reference.clip = fast.clip;
            for (a, b, width, color) in cases {
                stroke_segment_u8_at(&mut fast.surface(), a, b, width, color);

                let rgba = color.map(|channel| channel as f32 / 255.0);
                let hw = width * 0.5;
                let (x0, y0, x1, y1) = reference.bbox(
                    a.0.min(b.0) - hw - 1.0,
                    a.1.min(b.1) - hw - 1.0,
                    a.0.max(b.0) + hw + 1.0,
                    a.1.max(b.1) + hw + 1.0,
                );
                for y in y0..y1 {
                    for x in x0..x1 {
                        let coverage = seg_coverage((x as f32 + 0.5, y as f32 + 0.5), a, b, hw);
                        if coverage > 0.0 {
                            reference.blend(x, y, rgba, coverage);
                        }
                    }
                }
            }
            assert_eq!(fast.px, reference.px, "opaque={opaque}");
        }
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
    fn rotated_cw_text_walks_downward() {
        // "II" rotated CW from (20, 5): ink extends down the column below the
        // start point, and none is drawn above it.
        let mut cmd = vec![OP_TEXT];
        cmd.extend(f32le(20.0));
        cmd.extend(f32le(5.0));
        cmd.push(TEXT_ROTATED_CW); // anchor start, CW rotation
        cmd.extend(f32le(20.0)); // size
        cmd.extend([0, 0, 0, 255]);
        let s = b"II";
        cmd.extend(u32le(s.len() as u32));
        cmd.extend_from_slice(s);
        let mut out = vec![0u8; 40 * 40 * 4];
        assert!(rasterize_into(&cmd, 40, 40, &mut out));
        let ink_at = |lo: usize, hi: usize| -> u32 {
            (lo..hi)
                .flat_map(|y| (0..40).map(move |x| (y, x)))
                .map(|(y, x)| (out[(y * 40 + x) * 4 + 3] > 32) as u32)
                .sum()
        };
        assert_eq!(ink_at(0, 5), 0, "ink above the CW start point");
        assert!(ink_at(5, 40) > 5, "CW glyphs produced no ink below the start");
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
    fn banded_paint_matches_serial() {
        // Row-band fan-out must paint bit-identically to the serial pass, on
        // both canvas layouts, with a clip rect, and with an uneven last band.
        let (w, h) = (97, 61);
        let mut s = 0x2545f4914f6cdd1du64;
        let mut rnd = move || {
            s ^= s << 13;
            s ^= s >> 7;
            s ^= s << 17;
            (s >> 40) as f32 / 16777216.0
        };
        let n = 4000usize;
        let (mut xs, mut ys, mut rs, mut fills) = (Vec::new(), Vec::new(), Vec::new(), Vec::new());
        for i in 0..n {
            xs.extend(f32le(rnd() * (w as f32 + 8.0) - 4.0));
            ys.extend(f32le(rnd() * (h as f32 + 8.0) - 4.0));
            rs.extend(f32le(0.5 + rnd() * 3.0));
            fills.extend([
                (i * 37 % 256) as u8,
                (i * 101 % 256) as u8,
                (i * 197 % 256) as u8,
                if i % 3 == 0 {
                    255
                } else {
                    90 + (i % 100) as u8
                },
            ]);
        }
        // Non-finite backstop parity: x, y, and r NaNs must be skipped
        // identically by the serial loop and the bucketing pass.
        xs[0..4].copy_from_slice(&f32le(f32::NAN));
        ys[4..8].copy_from_slice(&f32le(f32::NAN));
        rs[8..12].copy_from_slice(&f32le(f32::NAN));
        let batch = PointsBatch {
            n,
            sym: 0,
            sw: 0.5,
            stroke: [10, 10, 10, 255],
            xs: &xs,
            ys: &ys,
            rs: &rs,
            fills: &fills,
        };
        let (mut sx0, mut sy0, mut sx1, mut sy1, mut colors) =
            (Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new());
        for i in 0..n {
            sx0.extend(f32le(rnd() * w as f32));
            sy0.extend(f32le(rnd() * h as f32));
            sx1.extend(f32le(rnd() * w as f32));
            sy1.extend(f32le(rnd() * h as f32));
            colors.extend([(i * 53 % 256) as u8, 30, 200, 180]);
        }
        let seg_batch = SegmentsBatch {
            n,
            width: 1.5,
            x0s: &sx0,
            y0s: &sy0,
            x1s: &sx1,
            y1s: &sy1,
            colors: &colors,
        };
        for opaque in [true, false] {
            for threads in [3usize, 8] {
                let mut serial = Canvas::new(w, h, opaque);
                serial.clip = [2.0, 3.0, w as f32 - 4.0, h as f32 - 2.0];
                let mut banded = Canvas::new(w, h, opaque);
                banded.clip = serial.clip;
                paint_points(&mut serial, &batch, 1);
                paint_points(&mut banded, &batch, threads);
                assert_eq!(
                    serial.px, banded.px,
                    "points opaque={opaque} threads={threads}"
                );
                let mut serial = Canvas::new(w, h, opaque);
                let mut banded = Canvas::new(w, h, opaque);
                paint_segments(&mut serial, &seg_batch, 1);
                paint_segments(&mut banded, &seg_batch, threads);
                assert_eq!(
                    serial.px, banded.px,
                    "segments opaque={opaque} threads={threads}"
                );
            }
        }
    }

    #[test]
    fn banded_polyline_stroke_matches_serial() {
        let points: Vec<(f32, f32)> = (0..700)
            .map(|i| {
                let x = -3.0 + i as f32 * 0.145;
                let y = 30.0 + (i as f32 * 0.19).sin() * 24.0 + (i as f32 * 0.037).cos() * 3.5;
                (x, y)
            })
            .collect();
        let rgba = [37.0 / 255.0, 99.0 / 255.0, 235.0 / 255.0, 0.61];
        for opaque in [false, true] {
            for (width, closed, dash) in [
                (0.6, false, &[][..]),
                (2.4, false, &[5.0, 2.0][..]),
                (1.5, true, &[3.0, 1.0, 1.0, 1.0][..]),
            ] {
                let mut serial = Canvas::new(101, 63, opaque);
                serial.clip = [2.0, 3.0, 98.0, 60.0];
                let mut banded = Canvas::new(101, 63, opaque);
                banded.clip = serial.clip;
                stroke_with_threads(&mut serial, &points, width, rgba, closed, dash, Some(1));
                stroke_with_threads(&mut banded, &points, width, rgba, closed, dash, Some(4));
                assert_eq!(
                    serial.px, banded.px,
                    "opaque={opaque} width={width} closed={closed} dash={dash:?}"
                );
            }
        }
    }

    #[test]
    fn banded_image_blit_matches_serial() {
        let (iw, ih) = (37usize, 23usize);
        let mut src = vec![0u8; iw * ih * 4];
        for (i, pixel) in src.chunks_exact_mut(4).enumerate() {
            pixel.copy_from_slice(&[
                (i * 37 % 256) as u8,
                (i * 101 % 256) as u8,
                (i * 197 % 256) as u8,
                (40 + i * 17 % 216) as u8,
            ]);
        }
        for opaque in [true, false] {
            for nearest in [true, false] {
                for threads in [3usize, 8] {
                    let mut serial = Canvas::new(97, 61, opaque);
                    serial.clip = [3.0, 2.0, 93.0, 59.0];
                    let mut banded = Canvas::new(97, 61, opaque);
                    banded.clip = serial.clip;
                    blit_with_threads(
                        &mut serial,
                        1.25,
                        -0.75,
                        94.5,
                        62.0,
                        iw,
                        ih,
                        &src,
                        nearest,
                        1,
                    );
                    blit_with_threads(
                        &mut banded,
                        1.25,
                        -0.75,
                        94.5,
                        62.0,
                        iw,
                        ih,
                        &src,
                        nearest,
                        threads,
                    );
                    assert_eq!(
                        serial.px, banded.px,
                        "opaque={opaque} nearest={nearest} threads={threads}"
                    );
                }
            }
        }
    }

    #[test]
    fn compact_density_image_matches_expanded_rgba() {
        let (iw, ih) = (7usize, 5usize);
        let encoded: Vec<u8> = (0..iw * ih)
            .map(|index| ((index * 47 + index / 3 * 19) % 256) as u8)
            .collect();
        let stops = [[68, 1, 84], [59, 82, 139], [33, 145, 140], [253, 231, 37]];
        let (maximum, opacity) = (10_000.0, 0.73);
        let mut rgba = vec![0u8; iw * ih * 4];
        assert!(crate::kernels::density_rgba_into(
            &encoded, iw, ih, maximum, &stops, opacity, &mut rgba,
        ));

        let (dx, dy, dw, dh) = (1.25, -0.75, 31.5, 23.25);
        let mut expanded = vec![OP_IMAGE];
        for value in [dx, dy, dw, dh] {
            expanded.extend(f32le(value));
        }
        expanded.extend(u32le(iw as u32));
        expanded.extend(u32le(ih as u32));
        expanded.push(0); // bilinear
        expanded.extend_from_slice(&rgba);

        let mut compact = vec![OP_DENSITY_IMAGE];
        for value in [dx, dy, dw, dh] {
            compact.extend(f32le(value));
        }
        compact.extend(u32le(iw as u32));
        compact.extend(u32le(ih as u32));
        compact.extend(u32le(0)); // external arena span
        compact.extend(0u64.to_le_bytes()); // external arena offset
        compact.extend(f64le(maximum));
        compact.extend(f64le(opacity));
        compact.extend(u32le(stops.len() as u32));
        for stop in stops {
            compact.extend(stop);
        }

        for opaque in [false, true] {
            let got = rasterize_with_spans(&compact, &[&encoded], 34, 24, opaque)
                .expect("compact density command");
            let want = rasterize_with_spans(&expanded, &[], 34, 24, opaque)
                .expect("expanded image command");
            assert_eq!(got.px, want.px, "opaque={opaque}");
        }

        let mut out = vec![0u8; 34 * 24 * 4];
        assert!(!rasterize_data_into(
            &compact,
            &encoded[..encoded.len() - 1],
            34,
            24,
            &mut out,
        ));
    }

    #[test]
    fn direct_heatmap_image_matches_expanded_rgba() {
        let (iw, ih) = (31usize, 17usize);
        let values: Vec<f32> = (0..iw * ih)
            .map(|index| match index % 37 {
                0 => f32::NAN,
                1 => 0.0,
                _ => ((index * 47 + 13) % 256) as f32 / 255.0,
            })
            .collect();
        let stops = [[68, 1, 84], [59, 82, 139], [33, 145, 140], [253, 231, 37]];
        let alpha = 187u8;
        let raw: Vec<f64> = values.iter().copied().map(f64::from).collect();
        let mut rgba = vec![0u8; iw * ih * 4];
        assert!(crate::kernels::heatmap_rgba_into(
            &raw, iw, ih, &stops, alpha, &mut rgba,
        ));

        let (dx, dy, dw, dh) = (1.25, -0.75, 15.5, 10.25);
        let mut expanded = vec![OP_IMAGE];
        for value in [dx, dy, dw, dh] {
            expanded.extend(f32le(value));
        }
        expanded.extend(u32le(iw as u32));
        expanded.extend(u32le(ih as u32));
        expanded.push(1); // nearest
        expanded.extend_from_slice(&rgba);

        let mut direct = vec![OP_HEATMAP_IMAGE];
        for value in [dx, dy, dw, dh] {
            direct.extend(f32le(value));
        }
        direct.extend(u32le(iw as u32));
        direct.extend(u32le(ih as u32));
        direct.extend(u32le(0)); // external arena span
        direct.extend(0u64.to_le_bytes()); // external arena offset
        direct.push(0); // normalized f32
        direct.extend(f64le(0.0));
        direct.extend(f64le(1.0));
        direct.push(alpha);
        direct.extend(u32le(stops.len() as u32));
        for stop in stops {
            direct.extend(stop);
        }
        let mut arena = Vec::with_capacity(values.len() * 4);
        for value in values {
            arena.extend(f32le(value));
        }

        for opaque in [false, true] {
            let got = rasterize_with_spans(&direct, &[&arena], 18, 11, opaque)
                .expect("direct heatmap command");
            let want = rasterize_with_spans(&expanded, &[], 18, 11, opaque)
                .expect("expanded image command");
            assert_eq!(got.px, want.px, "opaque={opaque}");
        }

        let mut canonical = vec![OP_HEATMAP_IMAGE];
        for value in [dx, dy, dw, dh] {
            canonical.extend(f32le(value));
        }
        canonical.extend(u32le(iw as u32));
        canonical.extend(u32le(ih as u32));
        canonical.extend(u32le(1)); // second external arena span
        canonical.extend(0u64.to_le_bytes());
        canonical.push(1); // canonical f64
        canonical.extend(f64le(0.0));
        canonical.extend(f64le(1.0));
        canonical.push(alpha);
        canonical.extend(u32le(stops.len() as u32));
        for stop in stops {
            canonical.extend(stop);
        }
        let mut canonical_arena = Vec::with_capacity(raw.len() * 8);
        for value in raw {
            canonical_arena.extend(f64le(value));
        }
        for opaque in [false, true] {
            let got =
                rasterize_with_spans(&canonical, &[b"unused", &canonical_arena], 18, 11, opaque)
                    .expect("canonical heatmap command");
            let want = rasterize_with_spans(&expanded, &[], 18, 11, opaque)
                .expect("expanded image command");
            assert_eq!(got.px, want.px, "canonical opaque={opaque}");
        }

        let mut out = vec![0u8; 18 * 11 * 4];
        assert!(!rasterize_data_into(
            &direct,
            &arena[..arena.len() - 1],
            18,
            11,
            &mut out,
        ));
    }

    #[test]
    fn stroked_triangles_match_expanded_commands_and_validate_wire() {
        let triangles = [
            (
                [3.0f32, 13.0, 7.0],
                [3.0f32, 4.0, 12.0],
                [211u8, 40, 61, 173],
            ),
            (
                [12.0f32, 21.0, 18.0],
                [10.0f32, 15.0, 22.0],
                [30u8, 144, 255, 211],
            ),
            (
                [5.0f32, 16.0, f32::NAN],
                [20.0f32, 25.0, 27.0],
                [90u8, 210, 80, 255],
            ),
        ];
        let width = 1.25f32;
        let stroke_color = [9u8, 17, 31, 229];
        let mut batch = vec![OP_STROKED_TRIANGLES];
        batch.extend(u32le(triangles.len() as u32));
        batch.extend(f32le(width));
        batch.extend(stroke_color);
        for coordinate in 0..6 {
            for (xs, ys, _) in triangles {
                let value = if coordinate % 2 == 0 {
                    xs[coordinate / 2]
                } else {
                    ys[coordinate / 2]
                };
                batch.extend(f32le(value));
            }
        }
        for (_, _, fill) in triangles {
            batch.extend(fill);
        }

        let mut expanded = Vec::new();
        for (xs, ys, fill) in triangles {
            expanded.push(OP_FILL_POLY);
            expanded.extend(u32le(3));
            for i in 0..3 {
                expanded.extend(f32le(xs[i]));
                expanded.extend(f32le(ys[i]));
            }
            expanded.extend(fill);
            expanded.push(OP_STROKE);
            expanded.extend(u32le(3));
            for i in 0..3 {
                expanded.extend(f32le(xs[i]));
                expanded.extend(f32le(ys[i]));
            }
            expanded.extend(f32le(width));
            expanded.extend(stroke_color);
            expanded.push(1); // closed
            expanded.extend(u32le(0)); // no dash
        }

        for opaque in [false, true] {
            let got = rasterize_with_spans(&batch, &[], 28, 30, opaque)
                .expect("batched stroked triangles");
            let want = rasterize_with_spans(&expanded, &[], 28, 30, opaque)
                .expect("expanded stroked triangles");
            assert_eq!(got.px, want.px, "opaque={opaque}");
        }

        let mut out = vec![0u8; 28 * 30 * 4];
        let mut bad_width = batch.clone();
        bad_width[5..9].copy_from_slice(&f32le(0.0));
        assert!(!rasterize_into(&bad_width, 28, 30, &mut out));
        assert!(!rasterize_into(&batch[..batch.len() - 1], 28, 30, &mut out));
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
    fn affine_points_match_expanded_batch_and_reject_bad_spans() {
        // Exercise nontrivial payload decode scales/offsets, two arenas with
        // nonzero byte offsets, inverted y pixels, render scaling, stroke,
        // transparency, and the non-finite backstop.
        let encoded_x = [-2.25f32, -0.5, 0.75, 2.0, f32::NAN];
        let encoded_y = [1.5f32, -1.0, 0.25, 2.25, 0.0];
        let x_decode = (0.25f64, 1_000.0f64);
        let y_decode = (2.0f64, -40.0f64);
        let x_map = [990.0f64, 1_010.0, 2.25, 37.5];
        let y_map = [-42.0f64, -38.0, 25.0, 1.5];
        let output_scale = 1.75f64;
        let (sym, sw, radius) = (3u8, 1.3125f32, 3.5f32);
        let (fill, stroke) = ([27u8, 119, 231, 143], [8u8, 9, 10, 211]);

        let mut x_arena = b"xpad".to_vec();
        let mut y_arena = b"ypad----".to_vec();
        for value in encoded_x {
            x_arena.extend(f32le(value));
        }
        for value in encoded_y {
            y_arena.extend(f32le(value));
        }

        let mut direct = vec![OP_AFFINE_POINTS];
        direct.extend(u32le(encoded_x.len() as u32));
        direct.push(sym);
        direct.extend(f32le(sw));
        direct.extend(stroke);
        direct.extend(f32le(radius));
        direct.extend(fill);
        direct.extend(u32le(0));
        direct.extend(4u64.to_le_bytes());
        direct.extend(f64le(x_decode.0));
        direct.extend(f64le(x_decode.1));
        direct.extend(u32le(1));
        direct.extend(8u64.to_le_bytes());
        direct.extend(f64le(y_decode.0));
        direct.extend(f64le(y_decode.1));
        for value in x_map.into_iter().chain(y_map) {
            direct.extend(f64le(value));
        }
        direct.extend(f64le(output_scale));

        let project = |encoded: f32, decode: (f64, f64), map: [f64; 4]| {
            let value = f64::from(encoded) / decode.0 + decode.1;
            let span = map[1] - map[0];
            let span = if span == 0.0 { 1.0 } else { span };
            ((map[2] + (value - map[0]) / span * (map[3] - map[2])) * output_scale) as f32
        };
        let xs: Vec<f32> = encoded_x
            .iter()
            .map(|&value| project(value, x_decode, x_map))
            .collect();
        let ys: Vec<f32> = encoded_y
            .iter()
            .map(|&value| project(value, y_decode, y_map))
            .collect();
        let mut expanded = vec![OP_POINTS];
        expanded.extend(u32le(encoded_x.len() as u32));
        expanded.push(sym);
        expanded.extend(f32le(sw));
        expanded.extend(stroke);
        for values in [&xs, &ys] {
            for &value in values {
                expanded.extend(f32le(value));
            }
        }
        for _ in encoded_x {
            expanded.extend(f32le(radius));
        }
        for _ in encoded_x {
            expanded.extend(fill);
        }

        for opaque in [false, true] {
            let got = rasterize_with_spans(&direct, &[&x_arena, &y_arena], 72, 52, opaque)
                .expect("borrowed affine points");
            let want =
                rasterize_with_spans(&expanded, &[], 72, 52, opaque).expect("expanded points");
            assert_eq!(got.px, want.px, "opaque={opaque}");
        }

        let mut out = vec![0u8; 72 * 52 * 4];
        assert!(!rasterize_spans_into(
            &direct,
            &[&x_arena[..x_arena.len() - 1], &y_arena],
            72,
            52,
            &mut out,
        ));
    }

    #[test]
    fn affine_channel_points_match_expanded_batch_and_validate_wire() {
        let x_values = [0.0f32, 0.5, 1.0];
        let y_values = [-1.0f32, 0.25, 1.0];
        let colors = [0.0f32, 0.5, 1.0];
        let sizes = [0.0f32, 0.4, 1.0];
        let mut arena = Vec::new();
        for values in [&x_values, &y_values, &colors, &sizes] {
            for &value in values {
                arena.extend(f32le(value));
            }
        }
        let x_map = [0.0f64, 1.0, 2.0, 30.0];
        let y_map = [-1.0f64, 1.0, 20.0, 2.0];
        let output_scale = 1.5f64;
        let (sym, sw, stroke, alpha) = (2u8, 0.75f32, [7u8, 8, 9, 211], 163u8);
        let stops = [[68u8, 1, 84], [33, 145, 140], [253, 231, 37]];

        let mut direct = vec![OP_AFFINE_CHANNEL_POINTS];
        direct.extend(u32le(3));
        direct.push(sym);
        direct.extend(f32le(sw));
        direct.extend(stroke);
        for offset in [0u64, 12] {
            direct.extend(u32le(0));
            direct.extend(offset.to_le_bytes());
            direct.extend(f64le(1.0));
            direct.extend(f64le(0.0));
        }
        for value in x_map.into_iter().chain(y_map) {
            direct.extend(f64le(value));
        }
        direct.extend(f64le(output_scale));
        direct.push(1); // continuous color
        direct.extend([0, 0, 0, alpha]);
        direct.push(0); // f32 color encoding
        direct.extend(u32le(0));
        direct.extend(24u64.to_le_bytes());
        direct.extend(u32le(stops.len() as u32));
        for stop in stops {
            direct.extend(stop);
        }
        direct.push(1); // continuous size
        direct.extend(u32le(0));
        direct.extend(36u64.to_le_bytes());
        direct.extend(f64le(2.0));
        direct.extend(f64le(8.0));

        let project = |value: f32, map: [f64; 4]| {
            ((map[2] + (f64::from(value) - map[0]) / (map[1] - map[0]) * (map[3] - map[2]))
                * output_scale) as f32
        };
        let xs: Vec<f32> = x_values
            .iter()
            .map(|&value| project(value, x_map))
            .collect();
        let ys: Vec<f32> = y_values
            .iter()
            .map(|&value| project(value, y_map))
            .collect();
        let radii: Vec<f32> = sizes
            .iter()
            .map(|&value| ((2.0 + 6.0 * f64::from(value)) / 2.0 * output_scale) as f32)
            .collect();
        let fills: Vec<[u8; 4]> = colors
            .iter()
            .map(|&value| crate::kernels::colormap_color(f64::from(value), &stops, alpha))
            .collect();
        let mut expanded = vec![OP_POINTS];
        expanded.extend(u32le(3));
        expanded.push(sym);
        expanded.extend(f32le(sw));
        expanded.extend(stroke);
        for values in [&xs, &ys, &radii] {
            for &value in values {
                expanded.extend(f32le(value));
            }
        }
        for fill in &fills {
            expanded.extend(fill);
        }

        for opaque in [false, true] {
            let got = rasterize_with_spans(&direct, &[&arena], 48, 36, opaque)
                .expect("borrowed affine channel points");
            let want = rasterize_with_spans(&expanded, &[], 48, 36, opaque)
                .expect("expanded styled points");
            assert_eq!(got.px, want.px, "opaque={opaque}");
        }

        let mut out = vec![0u8; 48 * 36 * 4];
        assert!(!rasterize_spans_into(
            &direct,
            &[&arena[..arena.len() - 1]],
            48,
            36,
            &mut out,
        ));

        // Categorical codes use the same affine command but borrow a compact
        // byte span.  Exact equality with an expanded point batch proves the
        // private typed wire does not change palette selection.
        let code_offset = arena.len() as u64;
        arena.extend([0u8, 1, 2]);
        let mut categorical = vec![OP_AFFINE_CHANNEL_POINTS];
        categorical.extend(u32le(3));
        categorical.push(sym);
        categorical.extend(f32le(sw));
        categorical.extend(stroke);
        for offset in [0u64, 12] {
            categorical.extend(u32le(0));
            categorical.extend(offset.to_le_bytes());
            categorical.extend(f64le(1.0));
            categorical.extend(f64le(0.0));
        }
        for value in x_map.into_iter().chain(y_map) {
            categorical.extend(f64le(value));
        }
        categorical.extend(f64le(output_scale));
        categorical.push(2); // categorical color
        categorical.extend([0, 0, 0, alpha]);
        categorical.push(1); // u8 color encoding
        categorical.extend(u32le(0));
        categorical.extend(code_offset.to_le_bytes());
        categorical.extend(u32le(stops.len() as u32));
        for stop in stops {
            categorical.extend(stop);
        }
        let constant_radius = 2.5f32;
        categorical.push(0); // constant size
        categorical.extend(f32le(constant_radius));

        let mut expanded_categories = vec![OP_POINTS];
        expanded_categories.extend(u32le(3));
        expanded_categories.push(sym);
        expanded_categories.extend(f32le(sw));
        expanded_categories.extend(stroke);
        for values in [&xs, &ys] {
            for &value in values {
                expanded_categories.extend(f32le(value));
            }
        }
        for _ in 0..3 {
            expanded_categories.extend(f32le(constant_radius));
        }
        for rgb in stops {
            expanded_categories.extend([rgb[0], rgb[1], rgb[2], alpha]);
        }
        let got = rasterize_with_spans(&categorical, &[&arena], 48, 36, false)
            .expect("borrowed u8 categorical points");
        let want = rasterize_with_spans(&expanded_categories, &[], 48, 36, false)
            .expect("expanded categorical points");
        assert_eq!(got.px, want.px);

        let mut bad_encoding = categorical;
        bad_encoding[147] = 2;
        assert!(!rasterize_spans_into(
            &bad_encoding,
            &[&arena],
            48,
            36,
            &mut out,
        ));
        let mut bad_mode = direct;
        bad_mode[142] = 3;
        assert!(!rasterize_spans_into(
            &bad_mode,
            &[&arena],
            48,
            36,
            &mut out,
        ));
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
