/**
 * fastcharts render client.
 *
 * A thin GPU render client (design dossier §32): receives a data-less spec +
 * offset-encoded f32 columns as raw binary (§29 — no JSON numbers, no parse),
 * uploads them once to WebGL2 buffers, and draws with instanced/point
 * primitives. Pan/zoom is a uniform update — it never touches data buffers (§7).
 *
 * Full scatter support:
 *  - per-point color: constant, continuous (colormap LUT), categorical (palette)
 *  - per-point size: constant or continuous (mapped to a px range)
 *  - GPU picking → exact-row hover tooltip (§7/§17 Tier-0 hover; exact values
 *    come from the kernel's f64 canonical store, §16)
 *  - Tier-2 density surface for massive scatter (§5): a kernel-binned count grid
 *    uploaded as a log-normalized R8 texture and colormapped at composite time,
 *    re-binned on zoom via a kernel round-trip (stale grid stays drawn until
 *    then, §17)
 *
 * Dependency-free: this file is the whole client. DOM is used only for chrome —
 * title, axis tick labels, legend, tooltip (§7).
 */

"use strict";

const PROTOCOL = 2;
// ---------------------------------------------------------------------------
// Colormaps (§36 — CVD-safe defaults). Compact stop lists; the client
// interpolates a 256-texel LUT texture once per colormap.
// ---------------------------------------------------------------------------

const COLORMAP_STOPS = {
  viridis: [
    [68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142], [38, 130, 142],
    [31, 158, 137], [53, 183, 121], [110, 206, 88], [181, 222, 43], [253, 231, 37],
  ],
  magma: [
    [0, 0, 4], [28, 16, 68], [79, 18, 123], [129, 37, 129], [181, 54, 122],
    [229, 80, 100], [251, 135, 97], [254, 194, 135], [252, 253, 191], [252, 253, 191],
  ],
  plasma: [
    [13, 8, 135], [84, 2, 163], [139, 10, 165], [185, 50, 137], [219, 92, 104],
    [244, 136, 73], [254, 188, 43], [240, 249, 33], [240, 249, 33], [240, 249, 33],
  ],
  cividis: [
    [0, 32, 76], [0, 42, 102], [39, 63, 108], [72, 85, 115], [106, 109, 120],
    [143, 133, 118], [181, 159, 105], [223, 187, 82], [253, 217, 63], [255, 233, 69],
  ],
  turbo: [
    [48, 18, 59], [70, 107, 227], [40, 187, 226], [61, 242, 148], [161, 253, 60],
    [232, 216, 33], [253, 149, 35], [225, 66, 13], [153, 15, 4], [122, 4, 3],
  ],
};

function buildLutData(name) {
  const stops = COLORMAP_STOPS[name] || COLORMAP_STOPS.viridis;
  const N = 256;
  const data = new Uint8Array(N * 4);
  for (let i = 0; i < N; i++) {
    const t = (i / (N - 1)) * (stops.length - 1);
    const lo = Math.floor(t);
    const hi = Math.min(lo + 1, stops.length - 1);
    const f = t - lo;
    for (let c = 0; c < 3; c++) {
      data[i * 4 + c] = Math.round(stops[lo][c] * (1 - f) + stops[hi][c] * f);
    }
    data[i * 4 + 3] = 255;
  }
  return data;
}

// ---------------------------------------------------------------------------
// Colors & theming (§36: chrome inherits CSS; marks read --chart-* tokens)
// ---------------------------------------------------------------------------

function resolveCssColor(host, expr) {
  const probe = document.createElement("span");
  probe.style.display = "none";
  probe.style.color = expr;
  host.appendChild(probe);
  const rgb = getComputedStyle(probe).color;
  host.removeChild(probe);
  const m = rgb.match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const parts = m[1].split(/[,/\s]+/).filter(Boolean).map(Number);
  const [r, g, b, a = 1] = parts;
  return [r / 255, g / 255, b / 255, a];
}

function cssToken(el, name) {
  const v = getComputedStyle(el).getPropertyValue(name).trim();
  return v || null;
}

function hexColor(hex) {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? [...h].map((c) => c + c).join("") : h;
  const n = parseInt(full.slice(0, 6), 16);
  const a = full.length === 8 ? parseInt(full.slice(6, 8), 16) / 255 : 1;
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255, a];
}

function parseColor(host, c, fallback) {
  if (!c) return fallback;
  if (c.startsWith("#")) return hexColor(c);
  return resolveCssColor(host, c) || fallback;
}

function readTheme(root) {
  const text = resolveCssColor(root, "currentColor") || [0.2, 0.2, 0.2, 1];
  const withA = (c, a) => [c[0], c[1], c[2], a];
  const tok = (name) => {
    const v = cssToken(root, name);
    return v ? resolveCssColor(root, v) || null : null;
  };
  return {
    bg: tok("--chart-bg"),
    grid: tok("--chart-grid") || withA(text, 0.14),
    axis: tok("--chart-axis") || withA(text, 0.55),
    label: tok("--chart-text") || withA(text, 0.85),
  };
}

function cssColor([r, g, b, a]) {
  return `rgba(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)},${a})`;
}

// ---------------------------------------------------------------------------
// Ticks (computed in f64 on the CPU — never through f32, §16)
// ---------------------------------------------------------------------------

function niceStep(rough) {
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  for (const m of [1, 2, 5, 10]) {
    if (rough <= m * mag * (1 + 1e-12)) return m * mag;
  }
  return 10 * mag;
}

function linearTicks(lo, hi, target = 6) {
  const step = niceStep((hi - lo) / target);
  const first = Math.ceil(lo / step) * step;
  const out = [];
  for (let v = first; v <= hi + step * 1e-9 && out.length < 200; v += step) {
    out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  }
  return { ticks: out, step };
}

const MS = { s: 1e3, m: 6e4, h: 36e5, d: 864e5 };
const TIME_STEPS = [
  1, 2, 5, 10, 20, 50, 100, 200, 500,
  MS.s, 2 * MS.s, 5 * MS.s, 10 * MS.s, 15 * MS.s, 30 * MS.s,
  MS.m, 2 * MS.m, 5 * MS.m, 10 * MS.m, 15 * MS.m, 30 * MS.m,
  MS.h, 2 * MS.h, 3 * MS.h, 6 * MS.h, 12 * MS.h,
  MS.d, 2 * MS.d, 7 * MS.d, 14 * MS.d,
];

function timeTicks(lo, hi, target = 6) {
  const span = hi - lo;
  const rough = span / target;
  if (rough > 14 * MS.d) return calendarTicks(lo, hi, rough);
  let step = TIME_STEPS[TIME_STEPS.length - 1];
  for (const s of TIME_STEPS) {
    if (s >= rough) { step = s; break; }
  }
  const first = Math.ceil(lo / step) * step;
  const out = [];
  for (let v = first; v <= hi && out.length < 200; v += step) out.push(v);
  return { ticks: out, step };
}

function calendarTicks(lo, hi, rough) {
  const monthsRough = rough / (30 * MS.d);
  const monthSteps = [1, 2, 3, 6, 12, 24, 60, 120];
  let stepM = monthSteps[monthSteps.length - 1];
  for (const s of monthSteps) {
    if (s >= monthsRough) { stepM = s; break; }
  }
  const d = new Date(lo);
  let y = d.getUTCFullYear();
  let m = d.getUTCMonth();
  m = Math.ceil(m / stepM) * stepM;
  const out = [];
  for (;;) {
    const t = Date.UTC(y + Math.floor(m / 12), m % 12, 1);
    if (t > hi) break;
    if (t >= lo) out.push(t);
    m += stepM;
    if (out.length > 1000) break;
  }
  return { ticks: out, step: stepM * 30 * MS.d };
}

function fmtTime(ms, step) {
  const d = new Date(ms);
  const pad = (n, w = 2) => String(n).padStart(w, "0");
  if (step >= 28 * MS.d) {
    const mo = d.getUTCMonth();
    return mo === 0 ? String(d.getUTCFullYear())
      : `${d.toLocaleString("en", { month: "short", timeZone: "UTC" })} ${d.getUTCFullYear()}`;
  }
  if (step >= MS.d) return `${d.toLocaleString("en", { month: "short", timeZone: "UTC" })} ${pad(d.getUTCDate())}`;
  if (step >= MS.m) return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  if (step >= MS.s) return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
  return `${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}.${pad(d.getUTCMilliseconds(), 3)}`;
}

function fmtLinear(v, step) {
  if (v === 0) return "0";
  const av = Math.abs(v);
  if (av >= 1e6 || av < 1e-4) return v.toExponential(1).replace("e+", "e");
  const dec = Math.max(0, -Math.floor(Math.log10(step)) + (step < 1 ? 1 : 0));
  let s = v.toFixed(Math.min(dec, 8));
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s;
}

function fmtValue(v, kind) {
  if (kind === "time_ms") {
    const d = new Date(v);
    return d.toISOString().replace("T", " ").replace(".000Z", "Z");
  }
  if (v === 0) return "0";
  const av = Math.abs(v);
  if (av >= 1e6 || av < 1e-4) return v.toExponential(3);
  return (Math.round(v * 1e4) / 1e4).toString();
}

// ---------------------------------------------------------------------------
// WebGL2 helpers
// ---------------------------------------------------------------------------

function compile(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    throw new Error("shader compile: " + gl.getShaderInfoLog(sh) + "\n" + src);
  }
  return sh;
}

function makeProgram(gl, vs, fs) {
  const p = gl.createProgram();
  gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs));
  gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
    throw new Error("program link: " + gl.getProgramInfoLog(p));
  }
  return p;
}

// Points: per-vertex position, plus optional per-vertex color scalar (a_cval)
// and size scalar (a_sval). Color mode selects how the LUT is sampled; the LUT
// is a 256×1 texture (colormap or cycled palette). Size mode maps a_sval into a
// px range. SDF-antialiased in the fragment stage.
const POINT_VS = `#version 300 es
in float ax; in float ay; in float a_cval; in float a_sval; in float a_sel; in float a_dval;
uniform vec2 u_xmap; uniform vec2 u_ymap;
uniform float u_size; uniform int u_sizeMode; uniform vec2 u_sizeRange;
uniform int u_colorMode; uniform float u_dpr; uniform int u_selActive;
out float v_lutCoord; out float v_dim; out float v_dval;
void main() {
  gl_Position = vec4(ax * u_xmap.x + u_xmap.y, ay * u_ymap.x + u_ymap.y, 0.0, 1.0);
  float sz = u_sizeMode == 1 ? mix(u_sizeRange.x, u_sizeRange.y, a_sval) : u_size;
  gl_PointSize = sz * u_dpr;
  // continuous: coord = value in [0,1]; categorical: center of texel a_cval.
  v_lutCoord = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
  // Local log-density LUT coord (drill handoff, §5): lets freshly drilled
  // points wear the density colormap so the texture->points swap is seamless.
  v_dval = a_dval;
  // Unselected marks dim when a selection is active (§34 selected/unselected styling).
  v_dim = (u_selActive == 1 && a_sel < 0.5) ? 0.12 : 1.0;
}`;

const POINT_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_color; uniform int u_colorMode; uniform sampler2D u_lut; uniform float u_opacity;
uniform sampler2D u_dlut; uniform float u_dblend;
in float v_lutCoord; in float v_dim; in float v_dval;
out vec4 outColor;
void main() {
  vec2 d = gl_PointCoord - 0.5;
  float r = length(d) * 2.0;
  float aa = fwidth(r) + 1e-4;
  float cov = 1.0 - smoothstep(1.0 - aa, 1.0, r);
  if (cov <= 0.001) discard;
  vec3 rgb = u_colorMode == 0 ? u_color.rgb : texture(u_lut, vec2(clamp(v_lutCoord, 0.0, 1.0), 0.5)).rgb;
  // Drill handoff (§5): near the density boundary, paint by local density with
  // the density ramp; ease into native colors as the zoom deepens (u_dblend->0).
  if (u_dblend > 0.001) {
    vec3 drgb = texture(u_dlut, vec2(clamp(v_dval, 0.0, 1.0), 0.5)).rgb;
    rgb = mix(rgb, drgb, u_dblend);
  }
  float alpha = cov * u_opacity * v_dim;
  outColor = vec4(rgb * alpha, alpha);
}`;

// Picking: same geometry + size, outputs an encoded ID (24-bit vertex index +
// 8-bit trace slot) so a single readPixels resolves which point is under the
// cursor (§17). Rerun's R-channel-ID-texture idea, RGBA8 variant.
const PICK_VS = `#version 300 es
in float ax; in float ay; in float a_sval;
uniform vec2 u_xmap; uniform vec2 u_ymap;
uniform float u_size; uniform int u_sizeMode; uniform vec2 u_sizeRange; uniform float u_dpr;
flat out int v_id;
void main() {
  gl_Position = vec4(ax * u_xmap.x + u_xmap.y, ay * u_ymap.x + u_ymap.y, 0.0, 1.0);
  float sz = u_sizeMode == 1 ? mix(u_sizeRange.x, u_sizeRange.y, a_sval) : u_size;
  gl_PointSize = max(sz, 6.0) * u_dpr; // enlarge hit target
  v_id = gl_VertexID;
}`;

const PICK_FS = `#version 300 es
precision highp float; precision highp int;
uniform int u_slot;
flat in int v_id;
out vec4 outColor;
void main() {
  vec2 d = gl_PointCoord - 0.5;
  if (length(d) > 0.5) discard;
  int id = v_id;
  outColor = vec4(
    float(id & 255) / 255.0,
    float((id >> 8) & 255) / 255.0,
    float((id >> 16) & 255) / 255.0,
    float(u_slot + 1) / 255.0
  );
}`;

// Density (Tier 2): a fullscreen quad; each fragment reconstructs its data-space
// coordinate from the view range, maps into the grid's data range, samples the
// pre-normalized log-density value, and colormaps (§5, §F6). Data outside the
// grid range is transparent — so a stale grid stays correctly positioned during
// pan until the re-bin arrives (§17).
const DENSITY_VS = `#version 300 es
in vec2 a_corner;
uniform vec4 u_view; // x0,x1,y0,y1
out vec2 v_data;
void main() {
  gl_Position = vec4(a_corner * 2.0 - 1.0, 0.0, 1.0);
  v_data = vec2(mix(u_view.x, u_view.y, a_corner.x), mix(u_view.z, u_view.w, a_corner.y));
}`;

const DENSITY_FS = `#version 300 es
precision highp float;
uniform sampler2D u_grid; uniform sampler2D u_lut;
uniform vec4 u_gridRange; // gx0,gx1,gy0,gy1
uniform float u_opacity;
in vec2 v_data;
out vec4 outColor;
void main() {
  vec2 uv = vec2((v_data.x - u_gridRange.x) / (u_gridRange.y - u_gridRange.x),
                 (v_data.y - u_gridRange.z) / (u_gridRange.w - u_gridRange.z));
  if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) discard;
  float t = texture(u_grid, uv).r;
  if (t <= 0.0) discard;
  vec3 rgb = texture(u_lut, vec2(clamp(t, 0.0, 1.0), 0.5)).rgb;
  float alpha = u_opacity * clamp(t * 1.35, 0.0, 1.0);
  if (alpha <= 0.01) discard;
  outColor = vec4(rgb * alpha, alpha);
}`;

const LINE_VS = `#version 300 es
in float ax0; in float ay0; in float ax1; in float ay1;
uniform vec2 u_xmap; uniform vec2 u_ymap; uniform vec2 u_res; uniform float u_width;
out float v_off;
const vec2 corners[4] = vec2[4](vec2(0.,-1.), vec2(0.,1.), vec2(1.,-1.), vec2(1.,1.));
void main() {
  vec2 p0 = vec2(ax0 * u_xmap.x + u_xmap.y, ay0 * u_ymap.x + u_ymap.y);
  vec2 p1 = vec2(ax1 * u_xmap.x + u_xmap.y, ay1 * u_ymap.x + u_ymap.y);
  vec2 pix0 = (p0 * 0.5 + 0.5) * u_res;
  vec2 pix1 = (p1 * 0.5 + 0.5) * u_res;
  vec2 dir = pix1 - pix0;
  float len = max(length(dir), 1e-6);
  dir /= len;
  vec2 n = vec2(-dir.y, dir.x);
  vec2 c = corners[gl_VertexID];
  float half_w = u_width * 0.5 + 0.5;
  vec2 pos = mix(pix0, pix1, c.x) + dir * (c.x * 2.0 - 1.0) * 0.5 + n * c.y * half_w;
  gl_Position = vec4(pos / u_res * 2.0 - 1.0, 0.0, 1.0);
  v_off = c.y * half_w;
}`;

const LINE_FS = `#version 300 es
precision highp float;
uniform vec4 u_color; uniform float u_width;
in float v_off;
out vec4 outColor;
void main() {
  float half_w = u_width * 0.5;
  float alpha = (1.0 - smoothstep(half_w - 0.5, half_w + 0.5, abs(v_off))) * u_color.a;
  if (alpha <= 0.001) discard;
  outColor = vec4(u_color.rgb * alpha, alpha);
}`;

// Candlestick: one instanced quad per candle, drawn twice per frame — the wick
// (low→high, thin) and the body (open↔close, wide). u_part selects which. A
// minimum 1px extent keeps doji (open==close) and flat wicks visible. Up/down
// color chosen per candle from a_dir. The rectangle primitive the bar /
// histogram / waterfall / error-bar family will share.
const CANDLE_VS = `#version 300 es
in float a_x; in float a_open; in float a_high; in float a_low; in float a_close; in float a_dir;
uniform vec2 u_xmap; uniform vec2 u_ymap; uniform vec2 u_res;
uniform float u_halfPx; uniform int u_part;
// part: 0 wick (low→high), 1 body (open↔close), 2 OHLC open tick (left),
//       3 OHLC close tick (right). Candlesticks use 0+1; OHLC bars use 0+2+3.
out float v_dir; out vec2 v_local; flat out float v_hpx;
const vec2 corners[4] = vec2[4](vec2(0.,0.), vec2(1.,0.), vec2(0.,1.), vec2(1.,1.));
void main() {
  float yLo, yHi;
  if (u_part == 1) { yLo = min(a_open, a_close); yHi = max(a_open, a_close); }
  else if (u_part == 2) { yLo = a_open; yHi = a_open; }   // flat open tick
  else if (u_part == 3) { yLo = a_close; yHi = a_close; } // flat close tick
  else { yLo = a_low; yHi = a_high; }
  float xcPx = ((a_x * u_xmap.x + u_xmap.y) * 0.5 + 0.5) * u_res.x;
  float ylPx = ((yLo * u_ymap.x + u_ymap.y) * 0.5 + 0.5) * u_res.y;
  float yhPx = ((yHi * u_ymap.x + u_ymap.y) * 0.5 + 0.5) * u_res.y;
  if (abs(yhPx - ylPx) < 1.0) { float mid = (ylPx + yhPx) * 0.5; ylPx = mid - 0.5; yhPx = mid + 0.5; }
  vec2 c = corners[gl_VertexID];
  // Ticks extend to one side of center; wick/body straddle it.
  float xL = u_part == 3 ? xcPx : xcPx - u_halfPx;
  float xR = u_part == 2 ? xcPx : xcPx + u_halfPx;
  float xPx = mix(xL, xR, c.x);
  float yPx = mix(ylPx, yhPx, c.y);
  gl_Position = vec4(vec2(xPx / u_res.x, yPx / u_res.y) * 2.0 - 1.0, 0.0, 1.0);
  v_dir = a_dir;
  v_local = c;           // 0..1 within the quad (for the hollow-body outline)
  v_hpx = abs(yhPx - ylPx);
}`;

const CANDLE_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_up; uniform vec4 u_down; uniform vec4 u_wick; uniform float u_opacity;
uniform float u_halfPx; uniform int u_isWick; uniform int u_wickFixed; uniform int u_hollowUp;
in float v_dir; in vec2 v_local; flat in float v_hpx;
out vec4 outColor;
void main() {
  bool up = v_dir > 0.5;
  vec3 rgb;
  if (u_isWick == 1) {
    rgb = u_wickFixed == 1 ? u_wick.rgb : (up ? u_up.rgb : u_down.rgb);
  } else {
    rgb = up ? u_up.rgb : u_down.rgb;
    // Hollow up-candles: keep a ~1px border, discard the interior.
    if (u_hollowUp == 1 && up) {
      float ex = min(v_local.x, 1.0 - v_local.x) * (u_halfPx * 2.0);
      float ey = min(v_local.y, 1.0 - v_local.y) * v_hpx;
      if (ex > 1.0 && ey > 1.0) discard;
    }
  }
  float a = u_opacity;
  outColor = vec4(rgb * a, a);
}`;
// ---------------------------------------------------------------------------

const LOD_DIRECT_POINT_BUDGET = 200000;
const LOD_DRILL_EXIT_FACTOR = 1.15;
// View-dependent LOD machinery (§5/§28) — chart-agnostic.
//
// Everything a tiered trace needs client-side, factored out of ChartView so a
// future heatmap/histogram tier reuses it instead of copy-pasting: the drill
// lifecycle (apply/refresh/dying/drop with entry+exit fades — restarting the
// entry fade per refresh, or dropping instantly, both read as flashing), the
// multi-window density-source cache, texture crossfades, and the eased
// "exposure" normalization. Functions take the owning ChartView as `view` and
// keep per-trace state on the trace's gpu record `g`; rendering stays in
// ChartView (lod calls back through view._drawDensity/_drawPoints so tests
// and future chart kinds can intercept/override the mark renderer).
// ---------------------------------------------------------------------------

function lodFade(view, start, duration = 140) {
  if (start === undefined || start === null || duration <= 0 || view._prefersReducedMotion()) {
    return 1;
  }
  const t = Math.min(1, Math.max(0, (performance.now() - start) / duration));
  return t * t * (3 - 2 * t);
}

function lodCopyGrid(f32) {
  return f32.slice ? f32.slice() : new Float32Array(f32);
}

// Log tone-mapped grid upload (R8): stable perception across renormalization,
// and the u_max swings between rebins compress logarithmically (§5/§F6).
function lodWriteGridTexture(gl, tex, f32, w, h, maxVal) {
  const data = new Uint8Array(f32.length);
  const denom = Math.log1p(Math.max(0, maxVal || 0));
  if (denom > 0) {
    for (let i = 0; i < f32.length; i++) {
      const c = f32[i];
      if (c > 0 && Number.isFinite(c)) {
        data[i] = Math.max(1, Math.min(255, Math.round(255 * Math.log1p(c) / denom)));
      }
    }
  }
  gl.bindTexture(gl.TEXTURE_2D, tex);
  const align = gl.getParameter(gl.UNPACK_ALIGNMENT);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, w, h, 0, gl.RED, gl.UNSIGNED_BYTE, data);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, align);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
}

// Treat the color scale like exposure: brighten slowly on drill-in so a
// smaller aggregate tile does not suddenly go hot, but recover faster when
// the incoming tile needs more headroom to avoid clipping.
function lodNormMax(g, nextMax) {
  if (!Number.isFinite(nextMax) || nextMax <= 0) {
    g.densityNormMax = 0;
    return 0;
  }
  const prev = Number.isFinite(g.densityNormMax) && g.densityNormMax > 0
    ? g.densityNormMax
    : nextMax;
  const norm = nextMax > prev
    ? prev * 0.3 + nextMax * 0.7
    : Math.max(nextMax, prev * 0.86);
  g.densityNormMax = norm;
  return norm;
}

function lodStartNormAnim(view, g, start, target) {
  if (!g.density || !g.density.grid || !Number.isFinite(target) || target <= 0) {
    g._densityNormAnim = null;
    return;
  }
  const ratio = Math.abs(Math.log(Math.max(start, 1e-12) / Math.max(target, 1e-12)));
  if (view._prefersReducedMotion() || ratio < 0.02) {
    g._densityNormAnim = null;
    g.density.normMax = target;
    g.densityNormMax = target;
    lodWriteGridTexture(view.gl, g.density.tex, g.density.grid, g.density.w, g.density.h, target);
    return;
  }
  g._densityNormAnim = {
    start,
    target,
    startedAt: performance.now(),
    duration: target < start ? 420 : 260,
  };
}

function lodStepNorm(view, g) {
  const anim = g._densityNormAnim;
  const d = g.density;
  if (!anim || !d || !d.grid || !d.tex) return;
  const t = Math.min(1, Math.max(0, (performance.now() - anim.startedAt) / anim.duration));
  const k = t * t * (3 - 2 * t);
  const norm = anim.start + (anim.target - anim.start) * k;
  const prev = d.normMax || 0;
  const rel = Math.abs(norm - prev) / Math.max(Math.abs(norm), Math.abs(prev), 1);
  if (rel > 0.004 || t >= 1) {
    d.normMax = norm;
    g.densityNormMax = norm;
    lodWriteGridTexture(view.gl, d.tex, d.grid, d.w, d.h, norm);
  }
  if (t < 1) {
    view.draw();
    return;
  }
  d.normMax = anim.target;
  g.densityNormMax = anim.target;
  g._densityNormAnim = null;
}

// -- density-source cache (multi-window LOD cache, §10) ----------------------

function lodDensityArea(d) {
  return Math.abs((d.xRange[1] - d.xRange[0]) * (d.yRange[1] - d.yRange[0]));
}

function lodWindowArea(win) {
  if (!win) return 0;
  return Math.abs((win.x1 - win.x0) * (win.y1 - win.y0));
}

function lodWindowCenterInside(win, view) {
  if (!win || !view) return false;
  const cx = (view.x0 + view.x1) / 2;
  const cy = (view.y0 + view.y1) / 2;
  return cx >= win.x0 && cx <= win.x1 && cy >= win.y0 && cy <= win.y1;
}

function lodDensityForView(view, g) {
  const cache = g.densityCache || (g.density ? [g.density] : []);
  let best = null;
  let broadest = null;
  for (const d of cache) {
    if (!d || !d.tex) continue;
    if (!broadest || lodDensityArea(d) > lodDensityArea(broadest)) broadest = d;
    if (!view._viewInsideRange(d.xRange, d.yRange)) continue;
    if (!best || lodDensityArea(d) < lodDensityArea(best)) best = d;
  }
  return best || broadest || g.density;
}

function lodHoldPendingDrill(view, g, d) {
  const pending = g._lodPendingView;
  if (!d || !pending || g._drillDying) return false;
  if (g._lodPendingSeq !== view.seq) return false;
  if (g._lodPendingAt && performance.now() - g._lodPendingAt > 1200) return false;
  if (!lodWindowCenterInside(d.win, pending)) return false;
  const drillArea = lodWindowArea(d.win);
  const pendingArea = lodWindowArea(pending);
  if (!Number.isFinite(drillArea) || !Number.isFinite(pendingArea) || drillArea <= 0) return false;
  const baseVisible = Number.isFinite(d.visible) ? d.visible : d.n;
  if (!Number.isFinite(baseVisible) || baseVisible <= 0) return false;
  const estimatedVisible = baseVisible * Math.max(1, pendingArea / drillArea);
  return estimatedVisible <= LOD_DIRECT_POINT_BUDGET * LOD_DRILL_EXIT_FACTOR;
}

function lodRememberDensity(view, g, d) {
  if (!d || !d.tex) return;
  d._stamp = ++view._densityStamp;
  if (!g.densityCache) g.densityCache = [];
  if (!g.densityCache.includes(d)) g.densityCache.push(d);
  const maxCached = 8;
  while (g.densityCache.length > maxCached) {
    let drop = -1;
    for (let i = 0; i < g.densityCache.length; i++) {
      const cand = g.densityCache[i];
      if (cand === g.density) continue;
      if (cand === g.prevDensity) continue;
      if (cand === g._densitySwitchPrev) continue;
      if (drop < 0) { drop = i; continue; }
      const dropArea = lodDensityArea(g.densityCache[drop]);
      const candArea = lodDensityArea(cand);
      if (candArea < dropArea || (candArea === dropArea && cand._stamp < g.densityCache[drop]._stamp)) {
        drop = i;
      }
    }
    if (drop < 0) break;
    const old = g.densityCache.splice(drop, 1)[0];
    if (old !== g.density && old !== g.prevDensity && old !== g._densitySwitchPrev) {
      view.gl.deleteTexture(old.tex);
    }
  }
}

// -- drill lifecycle ----------------------------------------------------------

// The kernel decided this view fits the direct budget and shipped real marks
// (channels restored). Build/refresh a direct-shaped sibling on the tiered
// trace; the tier draw uses it until the kernel switches back.
function lodApplyDrill(view, g, upd, buffers) {
  const gl = view.gl;
  const fresh = !g.drill; // transition INTO drill vs refresh of a live drill
  let d = g.drill;
  if (!d) {
    d = g.drill = { trace: g.trace, xBuf: gl.createBuffer(), yBuf: gl.createBuffer() };
  }
  gl.bindBuffer(gl.ARRAY_BUFFER, d.xBuf);
  gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.x.buf]), gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER, d.yBuf);
  gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.y.buf]), gl.STATIC_DRAW);
  d.xMeta = { offset: upd.x.offset, scale: upd.x.scale };
  d.yMeta = { offset: upd.y.offset, scale: upd.y.scale };
  d.win = { x0: upd.x_range[0], x1: upd.x_range[1], y0: upd.y_range[0], y1: upd.y_range[1] };
  d.n = Math.min(upd.x.len, upd.y.len);
  d.visible = upd.visible ?? d.n;
  d.seq = upd.drill_seq; // subset version — echoed with picks, gates selections
  d.selActive = false; // drilled subset changed; old mask indices are stale
  // The point under the cursor is a different row now; a cached tooltip for
  // the same index would silently show the old point's values (§16).
  view._hoverId = -1;
  view._lastRow = null;
  d.colorMode = 0;
  d.color = parseColor(view.root, upd.color && upd.color.color, [0.3, 0.47, 0.66, 1]);
  if (upd.color && upd.color.buf !== undefined) {
    d.colorMode = upd.color.mode === "continuous" ? 1 : 2;
    if (!d.cBuf) d.cBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, d.cBuf);
    gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.color.buf]), gl.STATIC_DRAW);
    d.lut = upd.color.mode === "continuous"
      ? view._lut(upd.color.colormap)
      : view._paletteLut(upd.color.palette);
  }
  d.sizeMode = 0;
  d.size = (upd.size && upd.size.size) || 4.0;
  d.sizeRange = [2, 18];
  if (upd.size && upd.size.mode === "continuous") {
    d.sizeMode = 1;
    if (!d.sBuf) d.sBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, d.sBuf);
    gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.size.buf]), gl.STATIC_DRAW);
    d.sizeRange = upd.size.range_px;
  }
  // Color-continuous handoff (§5): per-point local log-density + a blend
  // weight. Fresh at the boundary (blend≈1) the marks wear the aggregate's
  // colormap, so the texture->marks swap doesn't recolor the chart; deeper
  // zooms ship smaller blends and the native colors ease in.
  if (upd.density_val && upd.density_val.buf !== undefined) {
    if (!d.dBuf) d.dBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, d.dBuf);
    gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.density_val.buf]), gl.STATIC_DRAW);
    d.dlut = view._lut(upd.density_colormap || "viridis");
    const first = d.lodBlend === undefined;
    d.lodBlend = Math.min(1, upd.lod_blend ?? 0);
    if (first) d.lodBlendShown = d.lodBlend; // no tween-from-zero on arrival
  } else {
    d.lodBlend = 0;
  }
  // The entry fade runs ONLY on the aggregate→marks transition. Restarting it
  // on every refresh made the marks blink to ~0 alpha after each kernel
  // reply — a steady flash while zooming within a drilled view.
  if (fresh) g._drillFadeStart = performance.now();
  // A live points update revives a dying drill (hysteresis flip): cancel the
  // exit fade rather than fighting it.
  g._drillDying = false;
  g._drillExitFadeStart = null;
  g._drillWasInside = false;
}

function lodDropDrill(view, g) {
  const d = g.drill;
  if (!d) return;
  const gl = view.gl;
  for (const b of [d.xBuf, d.yBuf, d.cBuf, d.sBuf, d.selBuf, d.dBuf]) if (b) gl.deleteBuffer(b);
  g.drill = null;
  g._drillFadeStart = null;
  g._drillExitFadeStart = null;
  g._drillWasInside = false;
  g._drillDying = false;
  view._hoverId = -1; // drilled indices are dead; don't reuse a cached row
  view._lastRow = null;
}

// A density update arrived while drilled: don't drop the marks instantly
// (that hard-cuts the exit fade — a visible flash on drill-out). Mark the
// drill dying; the tier draw fades it over the incoming aggregate and frees
// it when the fade completes.
function lodMarkDrillDying(g) {
  if (!g.drill) return;
  g._drillDying = true;
  if (g._drillExitFadeStart == null) g._drillExitFadeStart = performance.now();
}

function lodDrillExitFade(view, g) {
  if (g._drillExitFadeStart === undefined || g._drillExitFadeStart === null) {
    g._drillExitFadeStart = performance.now();
  }
  const fade = lodFade(view, g._drillExitFadeStart, 120);
  if (fade >= 1) g._drillExitFadeStart = null;
  return fade;
}

// -- aggregate updates & tier drawing ----------------------------------------

// Apply a kernel "density"-mode update: new grid texture with eased exposure
// normalization, previous grid kept for the crossfade, source remembered in
// the per-trace cache.
function lodApplyDensityUpdate(view, g, upd, buffers) {
  lodMarkDrillDying(g);
  const d = upd.density;
  const grid = lodCopyGrid(view._asF32(buffers[d.buf]));
  const normStart = lodNormMax(g, d.max);
  const normMax = view._prefersReducedMotion() ? d.max : normStart;
  g.densityNormMax = normMax;
  g.prevDensity = g.density;
  g._densityFadeStart = performance.now();
  g.density = {
    w: d.w, h: d.h, max: d.max, normMax, colormap: d.colormap || g.density.colormap,
    xRange: d.x_range, yRange: d.y_range,
    grid,
    tex: view._uploadGrid(grid, d.w, d.h, normMax),
    lut: g.density.lut,
  };
  lodStartNormAnim(view, g, normMax, d.max);
  lodRememberDensity(view, g, g.density);
}

function lodDrawDensityWithFade(view, g, density, opacityScale = 1) {
  if (density !== g._shownDensity) {
    g._densitySwitchPrev = g._shownDensity;
    g._densitySwitchFadeStart = performance.now();
    g._shownDensity = density;
  }
  const prev = g._densitySwitchPrev;
  const fade = prev && prev.tex ? lodFade(view, g._densitySwitchFadeStart, 140) : 1;
  if (fade < 1) {
    view._drawDensity(g, prev, (1 - fade) * opacityScale);
    view._drawDensity(g, density, fade * opacityScale);
    view.draw();
    return;
  }
  if (fade >= 1) {
    if (g.prevDensity === g._densitySwitchPrev) g.prevDensity = null;
    g._densitySwitchPrev = null;
    g._densitySwitchFadeStart = null;
    if (density === g.density) g._densityFadeStart = null;
  }
  view._drawDensity(g, density, opacityScale);
}

// The tier's frame: marks alone while the view sits inside a live drilled
// window; aggregate + fading marks during transitions (drill-in entry fade,
// dying drill exit fade); aggregate alone otherwise. Never blank, never a
// hard cut (§5 smooth transitions).
function lodDrawDensityTier(view, g, x0, x1, y0, y1) {
  lodStepNorm(view, g);
  const d = g.drill;
  // A dying drill always takes the exit-fade path — even with the view still
  // inside its window — so the marks→aggregate handoff is a fade, never a cut.
  const inside = d && !g._drillDying && view._viewInside(d.win);
  const density = lodDensityForView(view, g);
  if (inside) {
    g._drillWasInside = true;
    g._drillExitFadeStart = null;
    const fade = lodFade(view, g._drillFadeStart);
    if (fade < 1 && density && density.tex) {
      view._drawDensity(g, density, 1 - fade);
      view._drawPoints(d, view._map(d.xMeta, x0, x1), view._map(d.yMeta, y0, y1), fade);
      view.draw();
    } else {
      g._drillFadeStart = null;
      view._drawPoints(d, view._map(d.xMeta, x0, x1), view._map(d.yMeta, y0, y1));
    }
  } else if (density && density.tex) {
    if (lodHoldPendingDrill(view, g, d)) {
      g._drillExitFadeStart = null;
      view._drawPoints(d, view._map(d.xMeta, x0, x1), view._map(d.yMeta, y0, y1));
      if (view._viewAnim) view.draw();
      return;
    }
    const exitingDrill = d && g._drillWasInside;
    const exitFade = exitingDrill ? lodDrillExitFade(view, g) : 1;
    if (exitingDrill && exitFade < 1) {
      lodDrawDensityWithFade(view, g, density, exitFade);
      view._drawPoints(d, view._map(d.xMeta, x0, x1), view._map(d.yMeta, y0, y1), 1 - exitFade);
      view.draw();
    } else {
      if (g._drillDying) lodDropDrill(view, g); // fade done: free the buffers
      else if (exitingDrill) g._drillWasInside = false;
      lodDrawDensityWithFade(view, g, density);
    }
  } else if (d) {
    view._drawPoints(d, view._map(d.xMeta, x0, x1), view._map(d.yMeta, y0, y1));
  }
}
// ---------------------------------------------------------------------------
// ChartView
// ---------------------------------------------------------------------------

const MARGIN = { l: 62, r: 14, t: 10, b: 42 };

class ChartView {
  constructor(el, spec, buffer, comm) {
    if (spec.protocol !== PROTOCOL) {
      el.textContent =
        `fastcharts: protocol mismatch (client speaks ${PROTOCOL}, kernel sent ${spec.protocol}). ` +
        "Update the fastcharts package and restart the kernel.";
      throw new Error("protocol mismatch");
    }
    this.spec = spec;
    this.comm = comm;
    this.seq = 0;
    this._densityStamp = 0;
    this._viewRequestBurstStart = null;
    this._viewAnim = null;
    this._animRaf = null;
    this._lastLabelDraw = null;
    this._lutCache = new Map();
    this._hoverId = -1;
    this.dragMode = "pan"; // "pan" | "zoom" (box zoom); toggled via the modebar

    // Responsive size: "100%" means the *container* owns that axis — measure
    // it now, track it with a ResizeObserver below. Numeric sizes are fixed.
    // (height:"100%" needs a parent with a defined height, per usual CSS.)
    this.fluid = spec.width === "100%";
    this.fluidH = spec.height === "100%";
    const rect = this.fluid || this.fluidH ? el.getBoundingClientRect() : null;
    const cw = this.fluid ? Math.round(rect.width) || 640 : spec.width; // 0 = hidden; RO corrects
    const ch = this.fluidH ? Math.round(rect.height) || 420 : spec.height;
    this.size = { w: Math.max(120, cw), h: Math.max(120, ch) };
    this._layout();

    this._buildDom(el);
    this.theme = readTheme(this.root);
    this._initGl(buffer);
    this._initInteraction();
    this._buildModebar(this.root); // after theme (icon color) + canvas (cursor)

    if ((this.fluid || this.fluidH) && typeof ResizeObserver !== "undefined") {
      this._ro = new ResizeObserver((entries) => {
        const r = entries[entries.length - 1].contentRect;
        if (r.width || r.height) this._resize(r.width, r.height);
      });
      this._ro.observe(this.root);
    }

    this.view0 = {
      x0: spec.x_axis.range[0], x1: spec.x_axis.range[1],
      y0: spec.y_axis.range[0], y1: spec.y_axis.range[1],
    };
    this.view = { ...this.view0 };

    this._themeWatch = window.matchMedia("(prefers-color-scheme: dark)");
    this._onScheme = () => this.refreshTheme();
    this._themeWatch.addEventListener?.("change", this._onScheme);

    if (comm) comm.onMessage((msg, buffers) => this._onKernelMsg(msg, buffers));
    this.draw();
  }

  _layout() {
    // Plot rect from the current size — margins fixed, data area flexes.
    const top = MARGIN.t + (this.spec.title ? 30 : 0);
    this.plot = {
      x: MARGIN.l,
      y: top,
      w: Math.max(40, this.size.w - MARGIN.l - MARGIN.r),
      h: Math.max(40, this.size.h - top - MARGIN.b),
    };
  }

  // Container size changed (fluid mode). Cheap on purpose: data GPU buffers
  // are untouched — the _map() uniforms absorb the new aspect — and the pick
  // FBO realloc is deferred to the next actual pick (_renderPick checks dims).
  // The view request re-decimates/re-bins at the new pixel size (§28), so a
  // bigger chart gains real detail, not just stretched pixels.
  _resize(cssW, cssH) {
    const w = this.fluid && cssW ? Math.max(120, Math.round(cssW)) : this.size.w;
    const h = this.fluidH && cssH ? Math.max(120, Math.round(cssH)) : this.size.h;
    if (w === this.size.w && h === this.size.h) return;
    this.size.w = w;
    this.size.h = h;
    this._layout();
    const p = this.plot;
    this.canvas.style.width = p.w + "px";
    this.canvas.style.height = p.h + "px";
    this.canvas.width = p.w * this.dpr;
    this.canvas.height = p.h * this.dpr;
    this.chrome.style.width = this.size.w + "px";
    this.chrome.style.height = this.size.h + "px";
    this.chrome.width = this.size.w * this.dpr;
    this.chrome.height = this.size.h * this.dpr;
    if (this._legend) this._legend.style.maxHeight = p.h - 12 + "px";
    this._pickDirty = true;
    this.draw();
    this._scheduleViewRequest();
  }

  _buildDom(el) {
    const s = this.spec;
    const root = document.createElement("div");
    root.className = "fastcharts";
    root.style.cssText =
      `position:relative;width:${this.fluid ? "100%" : this.size.w + "px"};` +
      `height:${this.fluidH ? "100%" : this.size.h + "px"};` +
      (this.fluidH ? "min-height:120px;" : "") + // parent without a height -> visible floor
      "font:12px system-ui,sans-serif;user-select:none;";
    el.appendChild(root);
    this.root = root;

    if (s.title) {
      const t = document.createElement("div");
      t.textContent = s.title;
      t.style.cssText =
        "position:absolute;top:6px;left:0;right:0;text-align:center;font-size:14px;font-weight:600;";
      root.appendChild(t);
    }

    this.chrome = document.createElement("canvas");
    this.chrome.style.cssText = "position:absolute;inset:0;pointer-events:none;";
    root.appendChild(this.chrome);

    this.canvas = document.createElement("canvas");
    this.canvas.style.cssText =
      `position:absolute;left:${this.plot.x}px;top:${this.plot.y}px;` +
      `width:${this.plot.w}px;height:${this.plot.h}px;cursor:crosshair;touch-action:none;`;
    root.appendChild(this.canvas);

    this.labels = document.createElement("div");
    this.labels.style.cssText = "position:absolute;inset:0;pointer-events:none;";
    root.appendChild(this.labels);

    // Hover tooltip (§17) — DOM, so it's crisp and selectable (§7).
    this.tooltip = document.createElement("div");
    this.tooltip.style.cssText =
      "position:absolute;display:none;pointer-events:none;z-index:5;" +
      "background:rgba(20,24,33,.92);color:#fff;padding:5px 8px;border-radius:4px;" +
      "font-size:11px;line-height:1.35;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,.3);";
    root.appendChild(this.tooltip);

    this._buildLegend(root);
  }

  _buildLegend(root) {
    const s = this.spec;
    if (s.show_legend === false) return;
    const items = [];
    for (const t of s.traces) {
      if (t.tier === "density") {
        items.push({ swatch: "gradient", cmap: t.density.colormap, name: t.name || "density" });
      } else if (t.kind === "candlestick") {
        if (t.name) items.push({ swatch: t.style.up_color, name: t.name });
      } else if (t.color && t.color.mode === "categorical") {
        t.color.categories.forEach((cat, i) =>
          items.push({ swatch: t.color.palette[i], name: cat }));
      } else if (t.color && t.color.mode === "continuous") {
        items.push({ swatch: "gradient", cmap: t.color.colormap, name: t.name || "value" });
      } else if (t.name) {
        const c = (t.color && t.color.color) || (t.style && t.style.color);
        items.push({ swatch: c, name: t.name });
      }
    }
    if (!items.length) return;
    const lg = document.createElement("div");
    lg.style.cssText =
      `position:absolute;top:${this.plot.y + 6}px;right:${MARGIN.r + 6}px;` +
      "display:flex;flex-direction:column;gap:2px;font-size:11px;" +
      "background:rgba(128,128,128,.08);border-radius:4px;padding:4px 8px;max-height:" +
      `${this.plot.h - 12}px;overflow:auto;`;
    for (const it of items) {
      const row = document.createElement("div");
      const sw = document.createElement("span");
      let bg = it.swatch;
      if (it.swatch === "gradient") {
        const stops = COLORMAP_STOPS[it.cmap] || COLORMAP_STOPS.viridis;
        bg = `linear-gradient(90deg,${stops.map((c) => `rgb(${c[0]},${c[1]},${c[2]})`).join(",")})`;
        sw.style.background = bg;
      } else {
        sw.style.background = bg;
      }
      sw.style.cssText +=
        "display:inline-block;width:12px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px;";
      row.appendChild(sw);
      row.appendChild(document.createTextNode(it.name));
      lg.appendChild(row);
    }
    root.appendChild(lg);
    this._legend = lg; // _resize refreshes its max-height
  }

  _initGl(buffer) {
    const dpr = window.devicePixelRatio || 1;
    this.dpr = dpr;
    this.canvas.width = this.plot.w * dpr;
    this.canvas.height = this.plot.h * dpr;
    this.chrome.width = this.size.w * dpr;
    this.chrome.height = this.size.h * dpr;
    this.chrome.style.width = this.size.w + "px";
    this.chrome.style.height = this.size.h + "px";

    const gl = this.canvas.getContext("webgl2", {
      antialias: false, premultipliedAlpha: true, alpha: true,
    });
    if (!gl) {
      this.root.textContent = "fastcharts: WebGL2 unavailable in this browser.";
      throw new Error("webgl2 unavailable");
    }
    this.gl = gl;
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    this.pointProg = makeProgram(gl, POINT_VS, POINT_FS);
    this.lineProg = makeProgram(gl, LINE_VS, LINE_FS);
    this.pickProg = makeProgram(gl, PICK_VS, PICK_FS);
    this.densityProg = makeProgram(gl, DENSITY_VS, DENSITY_FS);
    this.candleProg = makeProgram(gl, CANDLE_VS, CANDLE_FS);

    // Fullscreen quad for density.
    this.quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);

    this.gpuTraces = this.spec.traces.map((t) => this._buildTrace(buffer, t));
    this._pickable = this.gpuTraces.some((g) => markOf(g.trace.kind).pointPick && g.tier !== "density");
    if (this._pickable) this._initPickTarget();
  }

  _lut(name) {
    if (this._lutCache.has(name)) return this._lutCache.get(name);
    const gl = this.gl;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, buildLutData(name));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this._lutCache.set(name, tex);
    return tex;
  }

  _paletteLut(palette) {
    // Cached by palette identity: categorical drill updates request this per
    // zoom step, and an uncached texture per call is a steady GL leak.
    const key = "pal:" + palette.join(",");
    if (this._lutCache.has(key)) return this._lutCache.get(key);
    const gl = this.gl;
    const data = new Uint8Array(256 * 4);
    for (let i = 0; i < 256; i++) {
      const c = hexColor(palette[i % palette.length]);
      data[i * 4] = c[0] * 255;
      data[i * 4 + 1] = c[1] * 255;
      data[i * 4 + 2] = c[2] * 255;
      data[i * 4 + 3] = 255;
    }
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 256, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this._lutCache.set(key, tex);
    return tex;
  }

  _buildTrace(buffer, t) {
    const gl = this.gl;
    const g = { trace: t, tier: t.tier, color: [0.3, 0.47, 0.66, 1] };

    if (t.tier === "density") {
      const d = t.density;
      const grid = new Float32Array(buffer, this.spec.columns[d.buf].byte_offset, d.w * d.h);
      g.densityNormMax = d.max;
      g.density = {
        w: d.w, h: d.h, max: d.max, normMax: d.max, colormap: d.colormap,
        xRange: d.x_range, yRange: d.y_range,
        grid: lodCopyGrid(grid),
        tex: this._uploadGrid(grid, d.w, d.h, d.max),
        lut: this._lut(d.colormap),
      };
      g._shownDensity = g.density;
      lodRememberDensity(this, g, g.density);
      return g;
    }

    // Per-mark GPU setup is dispatched through MARK_KINDS (55_marks.js) so a
    // new chart kind is an entry in that registry, not another branch here.
    markOf(t.kind).build(this, g, t, buffer);
    return g;
  }

  // Shared (x,y) geometry setup for xy-shaped marks (scatter, line, area, …).
  // A mark whose geometry isn't a plain x/y pair (bars/candles have their own
  // vertex layout) skips this and uploads its own buffers in build().
  _buildXY(g, t, buffer) {
    const x = this._columnView(buffer, this.spec.columns[t.x]);
    const y = this._columnView(buffer, this.spec.columns[t.y]);
    g.xMeta = { ...this.spec.columns[t.x] };
    g.yMeta = { ...this.spec.columns[t.y] };
    g.n = Math.min(x.length, y.length);
    g.xBuf = this._upload(x);
    g.yBuf = this._upload(y);
  }

  _buildScatterMark(g, t, buffer) {
    this._buildXY(g, t, buffer);
    g.colorMode = 0;
    g.color = parseColor(this.root, t.color && t.color.color, [0.3, 0.47, 0.66, 1]);
    if (t.color && t.color.mode === "continuous") {
      g.colorMode = 1;
      g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
      g.lut = this._lut(t.color.colormap);
    } else if (t.color && t.color.mode === "categorical") {
      g.colorMode = 2;
      g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
      g.lut = this._paletteLut(t.color.palette);
    }
    g.sizeMode = 0;
    g.size = (t.size && t.size.size) || 4.0;
    g.sizeRange = [2, 18];
    if (t.size && t.size.mode === "continuous") {
      g.sizeMode = 1;
      g.sBuf = this._upload(this._columnView(buffer, this.spec.columns[t.size.buf]));
      g.sizeRange = t.size.range_px;
    }
  }

  _buildLineMark(g, t, buffer) {
    this._buildXY(g, t, buffer);
    g.color = parseColor(this.root, t.style && t.style.color, [0.3, 0.47, 0.66, 1]);
  }

  _buildCandleMark(g, t, buffer) {
    const col = (ref) => this._columnView(buffer, this.spec.columns[ref]);
    g.candle = {
      up: parseColor(this.root, t.style.up_color, [0.15, 0.65, 0.6, 1]),
      down: parseColor(this.root, t.style.down_color, [0.94, 0.33, 0.31, 1]),
      widthFrac: t.style.width_frac ?? 0.7,
      opacity: t.style.opacity ?? 1.0,
      hollow: !!t.style.hollow,
      wick: t.style.wick_color ? parseColor(this.root, t.style.wick_color, null) : null,
    };
    this._fillCandle(g, {
      x: col(t.x), o: col(t.open), h: col(t.high), l: col(t.low), c: col(t.close),
      xMeta: { ...this.spec.columns[t.x] },
      yMeta: { ...this.spec.columns[t.close] }, // OHLC share the y offset (§16)
    });
  }

  // Zoom re-decimation: refill the candle geometry from a kernel view update
  // (OHLC-bucketed for the new window). Reuses the same fill path as build.
  _applyCandleUpdate(g, upd, buffers) {
    if (!g.candle) return;
    this._fillCandle(g, {
      x: this._asF32(buffers[upd.x.buf]),
      o: this._asF32(buffers[upd.open.buf]),
      h: this._asF32(buffers[upd.high.buf]),
      l: this._asF32(buffers[upd.low.buf]),
      c: this._asF32(buffers[upd.close.buf]),
      xMeta: { kind: g.xMeta.kind, offset: upd.x.offset, scale: upd.x.scale },
      yMeta: { kind: g.yMeta.kind, offset: upd.close.offset, scale: upd.close.scale },
    });
    this.draw();
  }

  // Upload OHLC instance buffers + resident data-space copies (hover/slot
  // sizing), shared by first build and zoom re-decimation. `enc.*` are the
  // offset-encoded f32 arrays; metas carry the offset/scale to decode.
  _fillCandle(g, enc) {
    const gl = this.gl;
    g.xMeta = enc.xMeta;
    g.yMeta = enc.yMeta;
    g.n = Math.min(enc.x.length, enc.c.length);
    const dir = new Float32Array(g.n);
    for (let i = 0; i < g.n; i++) dir[i] = enc.c[i] >= enc.o[i] ? 1 : 0; // offset cancels
    const cd0 = g.candle;
    const set = (key, arr) => {
      if (!cd0[key]) cd0[key] = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, cd0[key]);
      gl.bufferData(gl.ARRAY_BUFFER, arr, gl.STATIC_DRAW);
    };
    set("xBuf", enc.x); set("oBuf", enc.o); set("hBuf", enc.h);
    set("lBuf", enc.l); set("cBuf", enc.c); set("dBuf", dir);
    const xo = g.xMeta.offset, yo = g.yMeta.offset;
    const xd = new Float64Array(g.n), od = new Float64Array(g.n), hd = new Float64Array(g.n);
    const ld = new Float64Array(g.n), cd = new Float64Array(g.n);
    for (let i = 0; i < g.n; i++) {
      xd[i] = enc.x[i] + xo; od[i] = enc.o[i] + yo; hd[i] = enc.h[i] + yo;
      ld[i] = enc.l[i] + yo; cd[i] = enc.c[i] + yo;
    }
    let dxMed = 1;
    if (g.n > 1) {
      const diffs = [];
      for (let i = 1; i < g.n; i++) diffs.push(xd[i] - xd[i - 1]);
      diffs.sort((a, b) => a - b);
      dxMed = diffs[diffs.length >> 1] || 1;
    }
    cd0.cpu = { x: xd, o: od, h: hd, l: ld, c: cd, dxMed };
  }

  _drawCandles(g, x0, x1, y0, y1) {
    const gl = this.gl;
    const prog = this.candleProg;
    gl.useProgram(prog);
    const u = (n) => gl.getUniformLocation(prog, n);
    const xm = this._map(g.xMeta, x0, x1);
    const ym = this._map(g.yMeta, y0, y1);
    gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
    gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
    gl.uniform2f(u("u_res"), this.canvas.width, this.canvas.height);
    const cd = g.candle;
    gl.uniform4f(u("u_up"), cd.up[0], cd.up[1], cd.up[2], 1);
    gl.uniform4f(u("u_down"), cd.down[0], cd.down[1], cd.down[2], 1);
    const wk = cd.wick || cd.up;
    gl.uniform4f(u("u_wick"), wk[0], wk[1], wk[2], 1);
    gl.uniform1i(u("u_wickFixed"), cd.wick ? 1 : 0);
    gl.uniform1f(u("u_opacity"), cd.opacity);
    // Candle slot in device px → body half-width; wick stays thin.
    const slotPx = (cd.cpu.dxMed / Math.max(x1 - x0, 1e-30)) * this.canvas.width;
    const bodyHalf = Math.max(0.5, slotPx * cd.widthFrac * 0.5);
    const wickHalf = Math.min(bodyHalf, Math.max(0.5 * this.dpr, 0.6 * this.dpr));
    const bind = (name, buf) => {
      const loc = gl.getAttribLocation(prog, name);
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 1, gl.FLOAT, false, 0, 0);
      gl.vertexAttribDivisor(loc, 1);
    };
    bind("a_x", cd.xBuf); bind("a_open", cd.oBuf); bind("a_high", cd.hBuf);
    bind("a_low", cd.lBuf); bind("a_close", cd.cBuf); bind("a_dir", cd.dBuf);
    gl.uniform1i(u("u_part"), 0); // wick
    gl.uniform1i(u("u_isWick"), 1);
    gl.uniform1i(u("u_hollowUp"), 0);
    gl.uniform1f(u("u_halfPx"), wickHalf);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n);
    gl.uniform1i(u("u_part"), 1); // body
    gl.uniform1i(u("u_isWick"), 0);
    gl.uniform1i(u("u_hollowUp"), cd.hollow ? 1 : 0);
    gl.uniform1f(u("u_halfPx"), bodyHalf);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n);
  }

  // OHLC bar variant: a thin vertical line (low→high) with a left open tick and
  // a right close tick — same data + program as the candle, tick geometry.
  _drawOHLC(g, x0, x1, y0, y1) {
    const gl = this.gl;
    const prog = this.candleProg;
    gl.useProgram(prog);
    const u = (n) => gl.getUniformLocation(prog, n);
    const xm = this._map(g.xMeta, x0, x1);
    const ym = this._map(g.yMeta, y0, y1);
    gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
    gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
    gl.uniform2f(u("u_res"), this.canvas.width, this.canvas.height);
    const cd = g.candle;
    gl.uniform4f(u("u_up"), cd.up[0], cd.up[1], cd.up[2], 1);
    gl.uniform4f(u("u_down"), cd.down[0], cd.down[1], cd.down[2], 1);
    gl.uniform1f(u("u_opacity"), cd.opacity);
    gl.uniform1i(u("u_isWick"), 0); // ticks + stem colored by up/down, filled
    gl.uniform1i(u("u_hollowUp"), 0);
    gl.uniform1i(u("u_wickFixed"), 0);
    const slotPx = (cd.cpu.dxMed / Math.max(x1 - x0, 1e-30)) * this.canvas.width;
    const tickPx = Math.max(1, slotPx * cd.widthFrac * 0.5);
    const stemHalf = Math.max(0.5 * this.dpr, 0.6 * this.dpr);
    const bind = (name, buf) => {
      const loc = gl.getAttribLocation(prog, name);
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 1, gl.FLOAT, false, 0, 0);
      gl.vertexAttribDivisor(loc, 1);
    };
    bind("a_x", cd.xBuf); bind("a_open", cd.oBuf); bind("a_high", cd.hBuf);
    bind("a_low", cd.lBuf); bind("a_close", cd.cBuf); bind("a_dir", cd.dBuf);
    const drawPart = (part, halfPx) => {
      gl.uniform1i(u("u_part"), part);
      gl.uniform1f(u("u_halfPx"), halfPx);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n);
    };
    drawPart(0, stemHalf); // low→high stem
    drawPart(2, tickPx); // open tick (left)
    drawPart(3, tickPx); // close tick (right)
  }

  _uploadGrid(f32, w, h, maxVal) {
    const gl = this.gl;
    const tex = gl.createTexture();
    lodWriteGridTexture(gl, tex, f32, w, h, maxVal);
    return tex;
  }

  // Grid tone-mapping, exposure normalization, source cache, and the drill
  // lifecycle live in 45_lod.js — chart-agnostic so future tiered kinds
  // (heatmap, histogram) reuse them instead of copy-pasting.

  _columnView(buffer, meta) {
    return new Float32Array(buffer, meta.byte_offset, meta.len);
  }

  _upload(f32) {
    const gl = this.gl;
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, f32, gl.STATIC_DRAW);
    return buf;
  }

  _initPickTarget() {
    const gl = this.gl;
    this.pickTex = gl.createTexture();
    this._allocPickTex();
    this.pickFbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.pickFbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.pickTex, 0);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this._pickDirty = true;
  }

  _allocPickTex() {
    // Sized to the canvas backing store; called again lazily after a resize
    // (from _renderPick, not _resize — no FBO churn during a drag-resize).
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.pickTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, this.canvas.width, this.canvas.height, 0,
      gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    this._pickW = this.canvas.width;
    this._pickH = this.canvas.height;
  }

  // -- drawing --------------------------------------------------------------

  _map(meta, lo, hi) {
    const mul = 2 / ((hi - lo) * meta.scale);
    const add = ((meta.offset - lo) / (hi - lo)) * 2 - 1;
    return [mul, add];
  }

  draw() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = null;
      this._drawNow();
    });
  }


  _drawNow() {
    const gl = this.gl;
    const { x0, x1, y0, y1 } = this.view;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    const bg = this.theme.bg;
    if (bg) gl.clearColor(bg[0] * bg[3], bg[1] * bg[3], bg[2] * bg[3], bg[3]);
    else gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);

    for (const g of this.gpuTraces) {
      if (g.tier === "density") {
        // Tier frame (drill/fades/cache) lives in 45_lod.js — chart-agnostic.
        lodDrawDensityTier(this, g, x0, x1, y0, y1);
        continue;
      }
      markOf(g.trace.kind).draw(this, g, x0, x1, y0, y1);
    }
    this._pickDirty = true;
    this._drawChrome();
  }

  _bindScalarAttr(prog, name, buf, byteOffset, divisor) {
    const gl = this.gl;
    const loc = gl.getAttribLocation(prog, name);
    if (loc < 0) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 1, gl.FLOAT, false, 0, byteOffset);
    gl.vertexAttribDivisor(loc, divisor);
  }

  _disableAttr(prog, name) {
    const gl = this.gl;
    const loc = gl.getAttribLocation(prog, name);
    if (loc >= 0) gl.disableVertexAttribArray(loc);
  }

  _drawPoints(g, xm, ym, opacityScale = 1) {
    const gl = this.gl;
    const prog = this.pointProg;
    gl.useProgram(prog);
    const u = (n) => gl.getUniformLocation(prog, n);
    gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
    gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
    gl.uniform1f(u("u_dpr"), this.dpr);
    gl.uniform1f(u("u_size"), g.size);
    gl.uniform1i(u("u_sizeMode"), g.sizeMode);
    gl.uniform2f(u("u_sizeRange"), g.sizeRange[0], g.sizeRange[1]);
    gl.uniform1i(u("u_colorMode"), g.colorMode);
    gl.uniform1f(u("u_opacity"), (g.trace.style.opacity ?? 0.8) * opacityScale);
    const [r, gg, b] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, 1);

    this._bindScalarAttr(prog, "ax", g.xBuf, 0, 0);
    this._bindScalarAttr(prog, "ay", g.yBuf, 0, 0);
    if (g.colorMode !== 0 && g.cBuf) {
      this._bindScalarAttr(prog, "a_cval", g.cBuf, 0, 0);
    } else {
      this._disableAttr(prog, "a_cval");
      const loc = gl.getAttribLocation(prog, "a_cval");
      if (loc >= 0) gl.vertexAttrib1f(loc, 0);
    }
    if (g.sizeMode === 1 && g.sBuf) {
      this._bindScalarAttr(prog, "a_sval", g.sBuf, 0, 0);
    } else {
      this._disableAttr(prog, "a_sval");
      const loc = gl.getAttribLocation(prog, "a_sval");
      if (loc >= 0) gl.vertexAttrib1f(loc, 0.5);
    }
    gl.uniform1i(u("u_selActive"), g.selActive ? 1 : 0);
    if (g.selActive && g.selBuf) {
      this._bindScalarAttr(prog, "a_sel", g.selBuf, 0, 0);
    } else {
      this._disableAttr(prog, "a_sel");
      const loc = gl.getAttribLocation(prog, "a_sel");
      if (loc >= 0) gl.vertexAttrib1f(loc, 1.0);
    }
    if (g.lut) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, g.lut);
      gl.uniform1i(u("u_lut"), 0);
    }
    // Drill handoff (§5): blend from the density ramp toward native colors.
    // The shown weight eases toward the kernel's target so successive drill
    // updates recolor smoothly instead of stepping. Time-based decay (τ=90ms)
    // — a per-frame factor would converge 2.4× faster on a 144Hz display.
    const blendTarget = g.lodBlend ?? 0;
    let blend = g.lodBlendShown ?? blendTarget;
    if (Math.abs(blend - blendTarget) > 0.005 && !this._prefersReducedMotion()) {
      const now = performance.now();
      const dt = g._blendTick ? Math.min(100, now - g._blendTick) : 16;
      g._blendTick = now;
      blend += (blendTarget - blend) * (1 - Math.exp(-dt / 90));
      g.lodBlendShown = blend;
      this.draw();
    } else {
      g.lodBlendShown = blend = blendTarget;
      g._blendTick = 0;
    }
    gl.uniform1f(u("u_dblend"), blend);
    if (blend > 0.001 && g.dBuf && g.dlut) {
      this._bindScalarAttr(prog, "a_dval", g.dBuf, 0, 0);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, g.dlut);
      gl.uniform1i(u("u_dlut"), 1);
    } else {
      this._disableAttr(prog, "a_dval");
      const loc = gl.getAttribLocation(prog, "a_dval");
      if (loc >= 0) gl.vertexAttrib1f(loc, 0);
      gl.uniform1i(u("u_dlut"), 1); // sampler must still point at a valid unit
    }
    gl.drawArrays(gl.POINTS, 0, g.n);
  }

  _drawDensity(g, density, opacityScale = 1) {
    const gl = this.gl;
    const prog = this.densityProg;
    gl.useProgram(prog);
    const u = (n) => gl.getUniformLocation(prog, n);
    const { x0, x1, y0, y1 } = this.view;
    gl.uniform4f(u("u_view"), x0, x1, y0, y1);
    const d = density || g.density;
    gl.uniform4f(u("u_gridRange"), d.xRange[0], d.xRange[1], d.yRange[0], d.yRange[1]);
    gl.uniform1f(u("u_opacity"), (g.trace.style.opacity ?? 1.0) * opacityScale);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, d.tex);
    gl.uniform1i(u("u_grid"), 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, d.lut);
    gl.uniform1i(u("u_lut"), 1);
    const loc = gl.getAttribLocation(prog, "a_corner");
    const maxAttrs = gl.getParameter(gl.MAX_VERTEX_ATTRIBS);
    for (let i = 0; i < maxAttrs; i++) gl.disableVertexAttribArray(i);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(loc, 0);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  _drawLine(g, xm, ym) {
    if (g.n < 2) return;
    const gl = this.gl;
    gl.useProgram(this.lineProg);
    const u = (n) => gl.getUniformLocation(this.lineProg, n);
    gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
    gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
    gl.uniform2f(u("u_res"), this.canvas.width, this.canvas.height);
    gl.uniform1f(u("u_width"), (g.trace.style.width || 1.5) * this.dpr);
    const [r, gg, b, a] = g.color;
    gl.uniform4f(u("u_color"), r, gg, b, a * (g.trace.style.opacity ?? 1));
    this._bindScalarAttr(this.lineProg, "ax0", g.xBuf, 0, 1);
    this._bindScalarAttr(this.lineProg, "ax1", g.xBuf, 4, 1);
    this._bindScalarAttr(this.lineProg, "ay0", g.yBuf, 0, 1);
    this._bindScalarAttr(this.lineProg, "ay1", g.yBuf, 4, 1);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n - 1);
  }

  _drawChrome() {
    const s = this.spec;
    const dpr = this.dpr;
    const ctx = this.chrome.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, this.size.w, this.size.h);
    const now = performance.now();
    const labelCadenceMs = this._viewAnim ? 80 : 0;
    const updateLabels = labelCadenceMs === 0
      || this._lastLabelDraw === null
      || now - this._lastLabelDraw >= labelCadenceMs;
    if (updateLabels) {
      this.labels.textContent = "";
      this._lastLabelDraw = now;
    }

    const { x0, x1, y0, y1 } = this.view;
    const p = this.plot;
    const xt = s.x_axis.kind === "time" ? timeTicks(x0, x1, Math.max(3, p.w / 90))
      : linearTicks(x0, x1, Math.max(3, p.w / 80));
    const yt = linearTicks(y0, y1, Math.max(3, p.h / 45));

    ctx.strokeStyle = cssColor(this.theme.grid);
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (const v of xt.ticks) {
      const px = p.x + ((v - x0) / (x1 - x0)) * p.w;
      ctx.moveTo(Math.round(px) + 0.5, p.y);
      ctx.lineTo(Math.round(px) + 0.5, p.y + p.h);
    }
    for (const v of yt.ticks) {
      const py = p.y + (1 - (v - y0) / (y1 - y0)) * p.h;
      ctx.moveTo(p.x, Math.round(py) + 0.5);
      ctx.lineTo(p.x + p.w, Math.round(py) + 0.5);
    }
    ctx.stroke();

    ctx.strokeStyle = cssColor(this.theme.axis);
    ctx.beginPath();
    ctx.moveTo(p.x + 0.5, p.y);
    ctx.lineTo(p.x + 0.5, p.y + p.h + 0.5);
    ctx.lineTo(p.x + p.w, p.y + p.h + 0.5);
    ctx.stroke();

    const label = (text, css) => {
      if (!updateLabels) return;
      const d = document.createElement("div");
      d.textContent = text;
      d.style.cssText = "position:absolute;color:" + cssColor(this.theme.label) + ";" + css;
      this.labels.appendChild(d);
    };
    for (const v of xt.ticks) {
      const px = p.x + ((v - x0) / (x1 - x0)) * p.w;
      if (px < p.x - 1 || px > p.x + p.w + 1) continue;
      const text = s.x_axis.kind === "time" ? fmtTime(v, xt.step) : fmtLinear(v, xt.step);
      label(text, `left:${px}px;top:${p.y + p.h + 6}px;transform:translateX(-50%);`);
    }
    for (const v of yt.ticks) {
      const py = p.y + (1 - (v - y0) / (y1 - y0)) * p.h;
      if (py < p.y - 1 || py > p.y + p.h + 1) continue;
      label(fmtLinear(v, yt.step), `right:${this.size.w - p.x + 8}px;top:${py}px;transform:translateY(-50%);`);
    }
    if (s.x_axis.label) {
      label(s.x_axis.label, `left:${p.x + p.w / 2}px;top:${p.y + p.h + 24}px;transform:translateX(-50%);font-weight:500;`);
    }
    if (s.y_axis.label) {
      label(s.y_axis.label,
        `left:10px;top:${p.y + p.h / 2}px;transform:rotate(-90deg) translateX(50%);transform-origin:left;font-weight:500;`);
    }
  }

  // -- crosshair (§17 read-out guides) --------------------------------------

  _buildCrosshair() {
    if (this.spec.show_crosshair === false) return;
    const col = cssColor(this.theme.axis);
    const line = (extra) => {
      const d = document.createElement("div");
      d.style.cssText =
        "position:absolute;display:none;pointer-events:none;z-index:3;" + extra;
      this.root.appendChild(d);
      return d;
    };
    // 1px guides; the label chips sit against the axes.
    this._xhV = line(`top:${this.plot.y}px;height:${this.plot.h}px;width:0;border-left:1px dashed ${col};`);
    this._xhH = line(`left:${this.plot.x}px;width:${this.plot.w}px;height:0;border-top:1px dashed ${col};`);
    const chip = "font:11px system-ui,sans-serif;padding:1px 4px;border-radius:3px;white-space:nowrap;" +
      `background:${cssColor(this.theme.axis)};color:#fff;`;
    this._xhXLab = line(chip);
    this._xhYLab = line(chip);
    this._crosshair = true;
  }

  _updateCrosshair(e) {
    if (!this._crosshair || this._transitionActive()) return this._hideCrosshair();
    const rect = this.canvas.getBoundingClientRect();
    const cy = e.clientY - rect.top; // css px within plot
    let cx = e.clientX - rect.left;
    if (cx < 0 || cx > this.plot.w || cy < 0 || cy > this.plot.h) return this._hideCrosshair();
    const { x0, x1, y0, y1 } = this.view;
    let dataX = x0 + (cx / this.plot.w) * (x1 - x0);
    const dataY = y1 - (cy / this.plot.h) * (y1 - y0);
    // Magnet: snap the vertical guide to the nearest candle (TradingView-style).
    let snapKind = this.spec.x_axis.kind;
    for (const g of this.gpuTraces) {
      const row = markOf(g.trace.kind).hover?.(this, g, dataX);
      if (row && row.x !== undefined) { dataX = row.x; snapKind = row.x_kind || snapKind; break; }
    }
    cx = ((dataX - x0) / (x1 - x0)) * this.plot.w;
    if (cx < -0.5 || cx > this.plot.w + 0.5) return this._hideCrosshair();
    const px = this.plot.x + cx, py = this.plot.y + cy;
    this._xhV.style.left = px + "px"; this._xhV.style.display = "block";
    this._xhH.style.top = py + "px"; this._xhH.style.display = "block";
    this._xhXLab.textContent = fmtValue(dataX, snapKind);
    this._xhXLab.style.left = px + "px";
    this._xhXLab.style.top = this.plot.y + this.plot.h + 4 + "px";
    this._xhXLab.style.transform = "translateX(-50%)";
    this._xhXLab.style.display = "block";
    this._xhYLab.textContent = fmtValue(dataY);
    this._xhYLab.style.left = this.plot.x + this.plot.w + 4 + "px";
    this._xhYLab.style.top = py + "px";
    this._xhYLab.style.transform = "translateY(-50%)";
    this._xhYLab.style.display = "block";
  }

  _hideCrosshair() {
    if (!this._crosshair) return;
    for (const el of [this._xhV, this._xhH, this._xhXLab, this._xhYLab]) el.style.display = "none";
  }

  _transitionActive() {
    const activeStart = (v) => v !== undefined && v !== null;
    return !!this._viewAnim || this.gpuTraces.some((g) =>
      activeStart(g._densityFadeStart) ||
      activeStart(g._densitySwitchFadeStart) ||
      activeStart(g._drillFadeStart) ||
      activeStart(g._drillExitFadeStart) ||
      !!g._densityNormAnim);
  }

  // -- picking (§17) --------------------------------------------------------

  _renderPick() {
    const gl = this.gl;
    if (this._pickW !== this.canvas.width || this._pickH !== this.canvas.height) {
      this._allocPickTex(); // deferred resize catch-up
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.pickFbo);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.disable(gl.BLEND);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    const { x0, x1, y0, y1 } = this.view;
    const prog = this.pickProg;
    gl.useProgram(prog);
    const u = (n) => gl.getUniformLocation(prog, n);
    gl.uniform1f(u("u_dpr"), this.dpr);
    let slot = 0;
    for (const g of this.gpuTraces) {
      // Density traces pick only while drilled to points (§5); the drill
      // sibling carries the buffers, the host g keeps the slot → trace id.
      const pg = g.tier === "density"
        ? (g.drill && !g._drillDying && this._viewInside(g.drill.win) ? g.drill : null)
        : (markOf(g.trace.kind).pointPick ? g : null);
      if (!pg || !pg.n) { g.pickSlot = -1; continue; } // stale slots must not alias
      const xm = this._map(pg.xMeta, x0, x1);
      const ym = this._map(pg.yMeta, y0, y1);
      gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
      gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
      gl.uniform1f(u("u_size"), pg.size);
      gl.uniform1i(u("u_sizeMode"), pg.sizeMode);
      gl.uniform2f(u("u_sizeRange"), pg.sizeRange[0], pg.sizeRange[1]);
      gl.uniform1i(u("u_slot"), slot);
      g.pickSlot = slot;
      this._bindScalarAttr(prog, "ax", pg.xBuf, 0, 0);
      this._bindScalarAttr(prog, "ay", pg.yBuf, 0, 0);
      if (pg.sizeMode === 1 && pg.sBuf) this._bindScalarAttr(prog, "a_sval", pg.sBuf, 0, 0);
      else {
        this._disableAttr(prog, "a_sval");
        const loc = gl.getAttribLocation(prog, "a_sval");
        if (loc >= 0) gl.vertexAttrib1f(loc, 0.5);
      }
      gl.drawArrays(gl.POINTS, 0, pg.n);
      slot++;
    }
    gl.enable(gl.BLEND);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this._pickDirty = false;
  }

  _pickAt(cssX, cssY) {
    if (!this._pickable) return null;
    if (this._pickDirty) this._renderPick();
    const gl = this.gl;
    const px = Math.round(cssX * this.dpr);
    const py = Math.round((this.plot.h - cssY) * this.dpr); // GL origin bottom-left
    if (px < 0 || py < 0 || px >= this.canvas.width || py >= this.canvas.height) return null;
    const buf = new Uint8Array(4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.pickFbo);
    gl.readPixels(px, py, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, buf);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    if (buf[3] === 0) return null;
    const slot = buf[3] - 1;
    const index = buf[0] | (buf[1] << 8) | (buf[2] << 16);
    const g = this.gpuTraces.find((t) => t.pickSlot === slot && markOf(t.trace.kind).pointPick);
    if (!g) return null;
    return { trace: g.trace.id, index, g };
  }

  _showTooltip(hit, clientX, clientY) {
    const row = this._localRow(hit);
    this._renderTooltip(row, clientX, clientY);
    if (this.comm) {
      // Exact f64 values from the kernel canonical store (§16). The local row
      // (decoded from f32) shows instantly; the exact one replaces it.
      // NOTE: picks use their own sequence — sharing this.seq with view
      // requests made a hover invalidate an in-flight tier_update, freezing
      // the stale tier (found in staff review).
      this._pickSeq = (this._pickSeq || 0) + 1;
      const req = { type: "pick", seq: this._pickSeq, trace: hit.trace, index: hit.index };
      // Drilled picks name the subset version they hit against; the kernel
      // returns None instead of translating through the wrong subset (§16/§17).
      const hg = hit.g;
      if (hg && hg.tier === "density" && hg.drill && hg.drill.seq !== undefined) {
        req.drill_seq = hg.drill.seq;
      }
      this.comm.send(req);
    }
  }

  _localRow(hit) {
    // Approximate readout from the resident f32 (used in standalone export and
    // as the instant value before the kernel's exact reply, §37). Only present
    // when CPU copies were retained (renderStandalone); the widget path replaces
    // this with the kernel's exact f64 row (§16).
    const g = hit.g;
    const cpu = g._cpu;
    const row = { trace: g.trace.id, index: hit.index };
    if (cpu) {
      row.x = cpu.x[hit.index] / (g.xMeta.scale || 1) + g.xMeta.offset;
      row.y = cpu.y[hit.index] / (g.yMeta.scale || 1) + g.yMeta.offset;
      row.x_kind = g.xMeta.kind;
      row.y_kind = g.yMeta.kind;
    }
    return row;
  }

  _renderTooltip(row, clientX, clientY) {
    if (!row) { this.tooltip.style.display = "none"; return; }
    const rect = this.root.getBoundingClientRect();
    const lx = clientX - rect.left;
    const ly = clientY - rect.top;
    const lines = [];
    if (row.x !== undefined) lines.push(`x: ${fmtValue(row.x, row.x_kind)}`);
    if (row.ohlc) {
      const o = row.ohlc;
      lines.push(`O ${fmtValue(o.o)}  H ${fmtValue(o.h)}`);
      lines.push(`L ${fmtValue(o.l)}  C ${fmtValue(o.c)}`);
    }
    if (row.y !== undefined) lines.push(`y: ${fmtValue(row.y, row.y_kind)}`);
    if (row.color_value !== undefined) lines.push(`color: ${fmtValue(row.color_value)}`);
    if (row.color_category !== undefined) lines.push(`${row.color_category}`);
    if (row.size_value !== undefined) lines.push(`size: ${fmtValue(row.size_value)}`);
    if (!lines.length) lines.push(`#${row.index}`);
    // Text nodes, not innerHTML: category labels are user data and must never
    // be parsed as markup (a category named "<img onerror=…>" is just a label).
    this.tooltip.textContent = "";
    lines.forEach((ln, i) => {
      if (i) this.tooltip.appendChild(document.createElement("br"));
      this.tooltip.appendChild(document.createTextNode(ln));
    });
    this.tooltip.style.display = "block";
    const tw = this.tooltip.offsetWidth;
    this.tooltip.style.left = Math.min(lx + 12, this.size.w - tw - 4) + "px";
    this.tooltip.style.top = ly + 12 + "px";
  }

  // -- interaction ----------------------------------------------------------

  _initInteraction() {
    const c = this.canvas;
    let drag = null;
    let band = null;

    // Rubber-band overlay for box-select (§34) — DOM, above the canvas.
    this.selRect = document.createElement("div");
    this.selRect.style.cssText =
      "position:absolute;display:none;pointer-events:none;z-index:4;" +
      "border:1px solid rgba(90,140,240,.9);background:rgba(90,140,240,.15);";
    this.root.appendChild(this.selRect);

    this._buildCrosshair();

    const dataAt = (clientX, clientY) => {
      const r = c.getBoundingClientRect();
      const fx = (clientX - r.left) / r.width;
      const fy = 1 - (clientY - r.top) / r.height;
      const { x0, x1, y0, y1 } = this.view;
      return [x0 + fx * (x1 - x0), y0 + fy * (y1 - y0)];
    };

    c.addEventListener("pointerdown", (e) => {
      this._cancelViewAnimation();
      // Shift-drag box-selects (§34); a "zoom" modebar toggle turns a plain drag
      // into a box-zoom; otherwise a plain drag pans.
      const mode = e.shiftKey && this._pickable ? "select"
        : this.dragMode === "zoom" ? "zoom" : null;
      if (mode) {
        band = { mode, sx: e.clientX, sy: e.clientY, d0: dataAt(e.clientX, e.clientY) };
        c.setPointerCapture(e.pointerId);
        this.tooltip.style.display = "none";
        return;
      }
      drag = { px: e.clientX, py: e.clientY, view: { ...this.view }, moved: false };
      c.setPointerCapture(e.pointerId);
      this.tooltip.style.display = "none";
      this._hideCrosshair();
    });
    c.addEventListener("pointermove", (e) => {
      if (band) { this._updateBand(band, e); return; }
      if (drag) {
        drag.moved = true;
        const { x0, x1, y0, y1 } = drag.view;
        const dx = ((e.clientX - drag.px) / this.plot.w) * (x1 - x0);
        const dy = ((e.clientY - drag.py) / this.plot.h) * (y1 - y0);
        this.view = { x0: x0 - dx, x1: x1 - dx, y0: y0 + dy, y1: y1 + dy };
        this.draw();
        this._scheduleViewRequest();
        return;
      }
      this._hover(e);
      this._updateCrosshair(e);
    });
    const end = (e) => {
      if (band) {
        this.selRect.style.display = "none";
        this._hideCrosshair();
        const d1 = dataAt(e.clientX, e.clientY);
        const moved = Math.abs(e.clientX - band.sx) > 3 || Math.abs(e.clientY - band.sy) > 3;
        if (moved) {
          if (band.mode === "zoom") this._zoomToBox(band.d0, d1, true);
          else this._sendSelect(band.d0, d1);
        }
        band = null;
        return;
      }
      if (drag && !drag.moved) this.tooltip.style.display = "none";
      drag = null;
    };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", () => {
      this.selRect.style.display = "none"; this._hideCrosshair(); band = null; drag = null;
    });
    c.addEventListener("pointerleave", () => {
      this.tooltip.style.display = "none"; this._hideCrosshair();
    });

    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      const f = Math.pow(1.0015, e.deltaY);
      const r = c.getBoundingClientRect();
      const fx = (e.clientX - r.left) / r.width;
      const fy = 1 - (e.clientY - r.top) / r.height;
      this._zoomAt(f, fx, fy, true, 95);
    }, { passive: false });

    c.addEventListener("dblclick", () => {
      this._clearSelection();
      this._setView(this.view0, { animate: true });
    });
  }

  _updateBand(band, e) {
    const rect = this.canvas.getBoundingClientRect();
    const rootRect = this.root.getBoundingClientRect();
    const x = Math.min(band.sx, e.clientX) - rootRect.left;
    const y = Math.min(band.sy, e.clientY) - rootRect.top;
    const w = Math.abs(e.clientX - band.sx);
    const h = Math.abs(e.clientY - band.sy);
    // clamp to plot area
    const px = this.plot.x, py = this.plot.y;
    const x2 = Math.min(x + w, px + this.plot.w), y2 = Math.min(y + h, py + this.plot.h);
    const cx = Math.max(x, px), cy = Math.max(y, py);
    if (band.mode === "zoom") {
      this.selRect.style.border = "1px solid rgba(120,120,120,.9)";
      this.selRect.style.background = "rgba(120,120,120,.12)";
    } else {
      this.selRect.style.border = "1px solid rgba(90,140,240,.9)";
      this.selRect.style.background = "rgba(90,140,240,.15)";
    }
    this.selRect.style.display = "block";
    this.selRect.style.left = cx + "px";
    this.selRect.style.top = cy + "px";
    this.selRect.style.width = Math.max(0, x2 - cx) + "px";
    this.selRect.style.height = Math.max(0, y2 - cy) + "px";
    void rect;
  }

  _sendSelect(d0, d1) {
    const x0 = Math.min(d0[0], d1[0]), x1 = Math.max(d0[0], d1[0]);
    const y0 = Math.min(d0[1], d1[1]), y1 = Math.max(d0[1], d1[1]);
    if (this.comm) {
      this.comm.send({ type: "select", x0, x1, y0, y1 });
    } else {
      this._selectLocal(x0, x1, y0, y1); // standalone: compute from resident f32
    }
  }

  // Standalone selection (no kernel): mask the retained CPU f32 columns (§37).
  _selectLocal(x0, x1, y0, y1) {
    let total = 0;
    for (const g of this.gpuTraces) {
      // _cpu only exists where the standalone entry retained copies (retainCpu).
      if (!g._cpu || g.tier === "density") continue;
      const cx = g._cpu.x, cy = g._cpu.y;
      const ox = g.xMeta.offset, sx = g.xMeta.scale || 1;
      const oy = g.yMeta.offset, sy = g.yMeta.scale || 1;
      const mask = new Float32Array(g.n);
      let cnt = 0;
      for (let i = 0; i < g.n; i++) {
        const dx = cx[i] / sx + ox, dy = cy[i] / sy + oy;
        if (dx >= x0 && dx <= x1 && dy >= y0 && dy <= y1) { mask[i] = 1; cnt++; }
      }
      this._applySelMask(g, mask);
      total += cnt;
    }
    this._selectionCount = total;
    this.draw();
  }

  _applySelMask(g, maskF32) {
    const gl = this.gl;
    if (!g.selBuf) g.selBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, g.selBuf);
    gl.bufferData(gl.ARRAY_BUFFER, maskF32, gl.STATIC_DRAW);
    g.selActive = true;
  }

  _clearSelection() {
    for (const g of this.gpuTraces) {
      g.selActive = false;
      if (g.drill) g.drill.selActive = false;
    }
    this._selectionCount = 0;
    if (this.comm) this.comm.send({ type: "select_clear" });
  }

  // -- modebar & zoom (Plotly-parity controls) ------------------------------

  _buildModebar(root) {
    if (this.spec.show_modebar === false) return;
    const bar = document.createElement("div");
    // Visible by default, then stronger on hover. At .25 opacity the controls
    // were technically present but easy to miss in embedded dashboards.
    bar.style.cssText =
      `position:absolute;top:${this.plot.y + 4}px;left:${this.plot.x + 4}px;z-index:6;` +
      "display:flex;gap:1px;opacity:.72;transition:opacity .15s;" +
      "background:rgba(255,255,255,.78);border:1px solid rgba(128,128,128,.18);" +
      "border-radius:4px;padding:1px;box-shadow:0 1px 4px rgba(0,0,0,.08);";
    root.addEventListener("pointerenter", () => { bar.style.opacity = "1"; });
    root.addEventListener("pointerleave", () => { bar.style.opacity = ".72"; });
    this._modebar = bar;
    this._modeBtns = {};

    const col = cssColor(this.theme.axis);
    const mk = (name, title, onClick, toggles) => {
      const b = document.createElement("button");
      b.type = "button";
      b.title = title;
      b.innerHTML = this._icon(name);
      b.style.cssText =
        "display:flex;align-items:center;justify-content:center;width:26px;height:24px;" +
        "padding:0;border:none;background:transparent;cursor:pointer;border-radius:3px;" +
        `color:${col};pointer-events:auto;`;
      b.addEventListener("pointerdown", (e) => e.stopPropagation());
      b.addEventListener("click", (e) => { e.stopPropagation(); onClick(); });
      bar.appendChild(b);
      if (toggles) this._modeBtns[toggles] = b;
      return b;
    };

    mk("zoomin", "Zoom in", () => this._zoomBy(0.5, true));
    mk("zoomout", "Zoom out", () => this._zoomBy(2, true));
    mk("pan", "Pan", () => this._setDragMode("pan"), "pan");
    mk("zoom", "Box zoom", () => this._setDragMode("zoom"), "zoom");
    mk("reset", "Reset view", () => {
      this._clearSelection();
      this._setView(this.view0, { animate: true });
    });
    root.appendChild(bar);
    this._setDragMode(this.dragMode);
  }

  _setDragMode(mode) {
    this.dragMode = mode;
    // Cursor telegraphs the gesture: grab for pan, crosshair for box-zoom.
    if (this.canvas) this.canvas.style.cursor = mode === "zoom" ? "crosshair" : "grab";
    for (const [name, btn] of Object.entries(this._modeBtns || {})) {
      btn.style.background = name === mode ? "rgba(128,128,128,.22)" : "transparent";
    }
  }

  _prefersReducedMotion() {
    return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
  }

  _cancelViewAnimation() {
    if (this._animRaf) cancelAnimationFrame(this._animRaf);
    this._animRaf = null;
    this._viewAnim = null;
  }

  _setView(next, opts = {}) {
    const target = { x0: next.x0, x1: next.x1, y0: next.y0, y1: next.y1 };
    const animate = opts.animate === true && !this._prefersReducedMotion();
    const duration = opts.duration || 180;
    if (!animate || duration <= 0) {
      this._cancelViewAnimation();
      this.view = target;
      this.draw();
      if (opts.request !== false) this._scheduleViewRequest();
      return;
    }

    clearTimeout(this._viewTimer);
    this.seq += 1; // invalidate in-flight LOD replies for the pre-animation view
    const request = opts.request !== false;
    const requestDelay = opts.requestDelay ?? Math.min(55, Math.max(24, duration * 0.35));
    const requestMaxWait = opts.requestMaxWait ?? 130;
    if (request) {
      this._scheduleViewRequest(target, { seq: this.seq, delay: requestDelay, maxWait: requestMaxWait });
    }
    const now = performance.now();
    const tau = Math.max(18, duration / 5);
    if (this._viewAnim) {
      this._viewAnim.target = target;
      this._viewAnim.tau = tau;
      return;
    }

    this._viewAnim = {
      target,
      last: now,
      tau,
    };
    const lerp = (a, b, t) => a + (b - a) * t;
    const span = (v) => Math.max(Math.abs(v.x1 - v.x0), Math.abs(v.y1 - v.y0), 1e-12);
    const closeEnough = (a, b) => {
      const tol = span(b) * 1e-4;
      return Math.max(
        Math.abs(a.x0 - b.x0), Math.abs(a.x1 - b.x1),
        Math.abs(a.y0 - b.y0), Math.abs(a.y1 - b.y1)) <= tol;
    };
    const step = (nowFrame) => {
      const anim = this._viewAnim;
      if (!anim) { this._animRaf = null; return; }
      const dt = Math.max(0, Math.min(64, nowFrame - anim.last));
      anim.last = nowFrame;
      const k = 1 - Math.exp(-dt / anim.tau);
      const t = closeEnough(this.view, anim.target) ? 1 : k;
      this.view = {
        x0: lerp(this.view.x0, anim.target.x0, t),
        x1: lerp(this.view.x1, anim.target.x1, t),
        y0: lerp(this.view.y0, anim.target.y0, t),
        y1: lerp(this.view.y1, anim.target.y1, t),
      };
      if (t < 1) {
        this.draw();
        this._animRaf = requestAnimationFrame(step);
      } else {
        this._animRaf = null;
        this._viewAnim = null;
        this.view = anim.target;
        this._lastLabelDraw = null;
        this.draw();
      }
    };
    this._animRaf = requestAnimationFrame(step);
  }

  // Center-anchored zoom (f<1 in, f>1 out) — the modebar buttons; wheel is
  // cursor-anchored. Shares the §16 precision floor so we never zoom past f32.
  _zoomBy(f, animate = false) {
    const base = this._viewAnim ? this._viewAnim.target : this.view;
    const { x0, x1, y0, y1 } = base;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    if (f < 1) {
      const minSpanX = Math.max(Math.abs(cx), 1e-30) * 1e-12;
      const minSpanY = Math.max(Math.abs(cy), 1e-30) * 1e-12;
      if ((x1 - x0) * f < minSpanX || (y1 - y0) * f < minSpanY) return;
    }
    this._setView({
      x0: cx - (cx - x0) * f, x1: cx + (x1 - cx) * f,
      y0: cy - (cy - y0) * f, y1: cy + (y1 - cy) * f,
    }, { animate });
  }

  _zoomAt(f, fx, fy, animate = false, duration = 120) {
    const base = this._viewAnim ? this._viewAnim.target : this.view;
    const { x0, x1, y0, y1 } = base;
    const ax = x0 + fx * (x1 - x0);
    const ay = y0 + fy * (y1 - y0);
    if (f < 1) {
      const minSpanX = Math.max(Math.abs(ax), 1e-30) * 1e-12;
      const minSpanY = Math.max(Math.abs(ay), 1e-30) * 1e-12;
      if ((x1 - x0) * f < minSpanX || (y1 - y0) * f < minSpanY) return;
    }
    this._setView({
      x0: ax - (ax - x0) * f, x1: ax + (x1 - ax) * f,
      y0: ay - (ay - y0) * f, y1: ay + (y1 - ay) * f,
    }, { animate, duration });
  }

  // Box-zoom: fit the view to the dragged data rectangle (§16 precision floor;
  // ignore degenerate drags that would collapse a span below f32 resolution).
  _zoomToBox(d0, d1, animate = false) {
    const x0 = Math.min(d0[0], d1[0]), x1 = Math.max(d0[0], d1[0]);
    const y0 = Math.min(d0[1], d1[1]), y1 = Math.max(d0[1], d1[1]);
    const minSpanX = Math.max(Math.abs(x0), Math.abs(x1), 1e-30) * 1e-12;
    const minSpanY = Math.max(Math.abs(y0), Math.abs(y1), 1e-30) * 1e-12;
    if (x1 - x0 < minSpanX || y1 - y0 < minSpanY) return;
    this._setView({ x0, x1, y0, y1 }, { animate });
  }

  _icon(name) {
    // Inline stroke SVGs (currentColor) — no external assets (§33 no supply chain).
    const svg = (body) =>
      `<svg width="15" height="15" viewBox="0 0 20 20" fill="none" ` +
      `stroke="currentColor" stroke-width="1.6" stroke-linecap="round" ` +
      `stroke-linejoin="round">${body}</svg>`;
    switch (name) {
      case "zoomin":
        return svg('<circle cx="8.5" cy="8.5" r="5.5"/><path d="M12.5 12.5 L17 17"/>' +
          '<path d="M8.5 6 V11 M6 8.5 H11"/>');
      case "zoomout":
        return svg('<circle cx="8.5" cy="8.5" r="5.5"/><path d="M12.5 12.5 L17 17"/>' +
          '<path d="M6 8.5 H11"/>');
      case "pan":
        return svg('<path d="M10 3 V17 M3 10 H17"/><path d="M10 3 L8 5 M10 3 L12 5"/>' +
          '<path d="M10 17 L8 15 M10 17 L12 15"/><path d="M3 10 L5 8 M3 10 L5 12"/>' +
          '<path d="M17 10 L15 8 M17 10 L15 12"/>');
      case "zoom":
        return svg('<rect x="3.5" y="3.5" width="13" height="13" rx="1" ' +
          'stroke-dasharray="3 2"/>');
      case "reset":
        return svg('<path d="M4 10 a6 6 0 1 1 1.8 4.3"/><path d="M4 6 V10 H8"/>');
      default:
        return svg("");
    }
  }

  _hover(e) {
    // Marks with their own hover (candlestick: CPU nearest-x readout) resolve
    // before the GPU point pick — no ID pass, works with no kernel attached.
    if (this._hoverNonPoint(e)) return;
    if (!this._pickable) return;
    if (this._transitionActive()) {
      this._hoverId = -1;
      this.tooltip.style.display = "none";
      return;
    }
    const rect = this.canvas.getBoundingClientRect();
    const hit = this._pickAt(e.clientX - rect.left, e.clientY - rect.top);
    if (!hit) {
      this._hoverId = -1;
      this.tooltip.style.display = "none";
      return;
    }
    const id = hit.trace * 1e9 + hit.index;
    this._lastHoverXY = { clientX: e.clientX, clientY: e.clientY };
    if (id === this._hoverId) {
      this._renderTooltip(this._lastRow, e.clientX, e.clientY);
      return;
    }
    this._hoverId = id;
    this._showTooltip(hit, e.clientX, e.clientY);
  }

  // CPU nearest-mark hover for kinds with a `hover` hook (candlestick). Returns
  // true if it handled the event (a hookable trace exists), so _hover skips the
  // GPU point pick. Reads exact resident values — no kernel round-trip (§17).
  _hoverNonPoint(e) {
    const traces = this.gpuTraces.filter((g) => markOf(g.trace.kind).hover);
    if (!traces.length) return false;
    const rect = this.canvas.getBoundingClientRect();
    const fx = (e.clientX - rect.left) / rect.width;
    const dataX = this.view.x0 + fx * (this.view.x1 - this.view.x0);
    let best = null;
    for (const g of traces) {
      const row = markOf(g.trace.kind).hover(this, g, dataX);
      if (row && (!best || row._dist < best._dist)) best = row;
    }
    if (!best) {
      this.tooltip.style.display = "none";
      return true;
    }
    this._renderTooltip(best, e.clientX, e.clientY);
    return true;
  }

  // Nearest candle to a data-space x → tooltip row of exact O/H/L/C.
  _candleHoverRow(g, dataX) {
    const cpu = g.candle && g.candle.cpu;
    if (!cpu || !g.n) return null;
    const xs = cpu.x;
    let lo = 0, hi = g.n - 1;
    while (lo < hi) { // binary search on sorted candle x
      const mid = (lo + hi) >> 1;
      if (xs[mid] < dataX) lo = mid + 1; else hi = mid;
    }
    if (lo > 0 && Math.abs(xs[lo - 1] - dataX) <= Math.abs(xs[lo] - dataX)) lo -= 1;
    // Ignore hovers more than half a slot from any candle.
    if (Math.abs(xs[lo] - dataX) > cpu.dxMed * 0.6) return null;
    return {
      x: xs[lo], x_kind: g.xMeta.kind, index: lo, _dist: Math.abs(xs[lo] - dataX),
      ohlc: { o: cpu.o[lo], h: cpu.h[lo], l: cpu.l[lo], c: cpu.c[lo] },
    };
  }

  _scheduleViewRequest(viewOverride = this.view, opts = {}) {
    if (!this.comm) return;
    const needsLine = this.spec.traces.some((t) => t.tier === "decimated");
    const needsDensity = this.gpuTraces.some((g) => g.tier === "density");
    if (!needsLine && !needsDensity) return;
    const seq = opts.seq ?? ++this.seq;
    const view = { ...viewOverride };
    const plotW = Math.round(this.plot.w);
    const plotH = Math.round(this.plot.h);
    if (needsDensity) {
      const now = performance.now();
      for (const g of this.gpuTraces) {
        if (g.tier !== "density") continue;
        g._lodPendingView = view;
        g._lodPendingSeq = seq;
        g._lodPendingAt = now;
      }
    }
    let delay = opts.delay ?? 120;
    if (opts.maxWait !== undefined && opts.maxWait !== null) {
      const now = performance.now();
      if (this._viewRequestBurstStart === undefined || this._viewRequestBurstStart === null) {
        this._viewRequestBurstStart = now;
      }
      const remaining = opts.maxWait - (now - this._viewRequestBurstStart);
      delay = remaining <= 0 ? 0 : Math.min(delay, remaining);
    } else {
      this._viewRequestBurstStart = null;
    }
    clearTimeout(this._viewTimer);
    const send = () => {
      this._viewRequestBurstStart = null;
      if (seq !== this.seq) return;
      if (needsLine) {
        this.comm.send({
          type: "view", seq,
          x0: view.x0, x1: view.x1, px: plotW,
        });
      }
      if (needsDensity) {
        for (const g of this.gpuTraces) {
          if (g.tier !== "density") continue;
          this.comm.send({
            type: "density_view", seq, trace: g.trace.id,
            x0: view.x0, x1: view.x1, y0: view.y0, y1: view.y1,
            w: plotW, h: plotH,
          });
        }
      }
    };
    if (delay <= 0) {
      send();
    } else {
      this._viewTimer = setTimeout(send, delay);
    }
    return seq;
  }

  _onKernelMsg(msg, buffers) {
    if (!msg) return;
    if (msg.type === "tier_update") {
      if (msg.seq !== this.seq) return;
      for (const upd of msg.traces) {
        const g = this.gpuTraces.find((t) => t.trace.id === upd.id);
        if (!g) continue;
        if (upd.kind === "candlestick" || upd.kind === "ohlc") {
          this._applyCandleUpdate(g, upd, buffers); continue;
        }
        const gl = this.gl;
        gl.bindBuffer(gl.ARRAY_BUFFER, g.xBuf);
        gl.bufferData(gl.ARRAY_BUFFER, this._asF32(buffers[upd.x.buf]), gl.STATIC_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, g.yBuf);
        gl.bufferData(gl.ARRAY_BUFFER, this._asF32(buffers[upd.y.buf]), gl.STATIC_DRAW);
        g.xMeta = { ...g.xMeta, offset: upd.x.offset, scale: upd.x.scale };
        g.yMeta = { ...g.yMeta, offset: upd.y.offset, scale: upd.y.scale };
        g.n = Math.min(upd.x.len, upd.y.len);
      }
      this.draw();
    } else if (msg.type === "density_update") {
      if (msg.seq !== undefined && msg.seq !== this.seq) return;
      for (const upd of msg.traces) {
        const g = this.gpuTraces.find((t) => t.trace.id === upd.id && t.tier === "density");
        if (!g) continue;
        if (msg.seq === undefined || g._lodPendingSeq === msg.seq) {
          g._lodPendingView = null;
          g._lodPendingSeq = null;
          g._lodPendingAt = null;
        }
        if (upd.mode === "points") { this._applyDrill(g, upd, buffers); continue; }
        lodApplyDensityUpdate(this, g, upd, buffers);
      }
      // Drill state changes what's pickable; hover needs the FBO ready.
      this._pickable = this.gpuTraces.some(
        (t) => markOf(t.trace.kind).pointPick && (t.tier !== "density" || t.drill));
      if (this._pickable && !this.pickFbo) this._initPickTarget();
      this.draw();
    } else if (msg.type === "pick_result") {
      if (!msg.row) { this.tooltip.style.display = "none"; return; }
      this._lastRow = msg.row;
      const xy = this._lastHoverXY;
      if (xy) this._renderTooltip(msg.row, xy.clientX, xy.clientY);
    } else if (msg.type === "selection") {
      if (!msg.traces || !msg.traces.length) {
        for (const g of this.gpuTraces) {
          g.selActive = false;
          if (g.drill) g.drill.selActive = false;
        }
      } else {
        for (const upd of msg.traces) {
          const g = this.gpuTraces.find((t) => t.trace.id === upd.id);
          if (!g) continue;
          // Aggregate density has no per-point marks, but a drilled view does —
          // the kernel's indices are in the drilled subset's space (§17).
          const pg = g.tier === "density" ? g.drill : g;
          if (!pg || !pg.n) continue;
          // A mask built against another subset version would highlight
          // arbitrary points — drop it; the kernel's canonical Selection is
          // still correct and a fresh drag re-syncs the visual.
          if (
            g.tier === "density" && upd.drill_seq !== undefined &&
            pg.seq !== undefined && upd.drill_seq !== pg.seq
          ) continue;
          const idx = this._asU32(buffers[upd.buf]);
          const mask = new Float32Array(pg.n);
          for (let i = 0; i < idx.length; i++) if (idx[i] < pg.n) mask[idx[i]] = 1;
          this._applySelMask(pg, mask);
        }
      }
      this._selectionCount = msg.total || 0;
      this.draw();
    }
  }

  // -- Tier-2 drill-in (§5: tier follows the *visible* count) ---------------

  // Drill lifecycle, exit fades, and the density-source cache live in
  // 45_lod.js (chart-agnostic). These delegates keep the ChartView API
  // stable for tests and callers.
  _applyDrill(g, upd, buffers) {
    lodApplyDrill(this, g, upd, buffers);
  }

  _dropDrill(g) {
    lodDropDrill(this, g);
  }

  // Is the current view fully covered by a drilled window? A tiny epsilon
  // absorbs f32 round-trip slop so we don't flip to the overview at the exact
  // window edge right after drilling in.
  _viewInside(win) {
    if (!win) return false;
    const { x0, x1, y0, y1 } = this.view;
    const ex = (x1 - x0) * 1e-4, ey = (y1 - y0) * 1e-4;
    return x0 >= win.x0 - ex && x1 <= win.x1 + ex && y0 >= win.y0 - ey && y1 <= win.y1 + ey;
  }

  _viewInsideRange(xRange, yRange) {
    if (!xRange || !yRange) return false;
    return this._viewInside({ x0: xRange[0], x1: xRange[1], y0: yRange[0], y1: yRange[1] });
  }

  _asF32(b) {
    if (b instanceof ArrayBuffer) return new Float32Array(b);
    if (b.byteOffset % 4 === 0) {
      return new Float32Array(b.buffer, b.byteOffset, Math.floor(b.byteLength / 4));
    }
    return new Float32Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
  }

  _asU32(b) {
    if (b instanceof ArrayBuffer) return new Uint32Array(b);
    if (b.byteOffset % 4 === 0) {
      return new Uint32Array(b.buffer, b.byteOffset, Math.floor(b.byteLength / 4));
    }
    return new Uint32Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
  }

  refreshTheme() {
    this.theme = readTheme(this.root);
    for (const g of this.gpuTraces) {
      // Re-resolve CSS-expressed constant colors (§36 live re-resolution);
      // each mark kind knows where its constant color lives in the spec.
      markOf(g.trace.kind).refreshColor?.(this, g);
    }
    this.draw();
  }

  destroy() {
    this._ro?.disconnect();
    this._themeWatch?.removeEventListener?.("change", this._onScheme);
    clearTimeout(this._viewTimer);
    if (this._raf) cancelAnimationFrame(this._raf);
    this._cancelViewAnimation();
    for (const g of this.gpuTraces || []) {
      const seen = new Set();
      for (const d of g.densityCache || []) {
        if (d && d.tex && !seen.has(d.tex)) {
          seen.add(d.tex);
          this.gl.deleteTexture(d.tex);
        }
      }
    }
    this.root.remove();
  }
}
// ---------------------------------------------------------------------------
// Mark-renderer registry — the client-side dispatch for chart kinds.
//
// Mirrors the kernel's `_emit_<kind>` dispatch (figure.py) so the two sides
// stay symmetric: adding a 2D chart is an entry here plus an `_emit_<kind>`,
// not another branch inside ChartView. A renderer owns two steps for its kind:
//
//   build(view, g, trace, buffer)   — GPU setup: upload geometry/attribute
//                                     buffers onto the gpu record `g`. Reuse
//                                     view._buildXY for plain (x,y) marks; a
//                                     mark with its own vertex layout (bars,
//                                     candles) uploads its own buffers.
//   draw(view, g, x0, x1, y0, y1)   — one frame in the current data window.
//                                     xy marks map with view._map(); a mark
//                                     with a different transform maps itself.
//
// Tiering is orthogonal: a density-tier trace is handled by 45_lod.js before
// this registry is consulted (its drilled marks still render as points today).
// Picking and legend swatches are separate extension points documented in
// docs/chart-kind-contract.md — generalize them when a pickable non-point
// mark actually lands, not preemptively.
// ---------------------------------------------------------------------------

// Capabilities (beyond build/draw) so no per-kind knowledge leaks back into
// ChartView branches:
//   pointPick    — marks are point-shaped and participate in the GPU ID pick
//                  pass (§17). A future rect/candle mark supplies its own pick
//                  step instead (see docs/chart-kind-contract.md).
//   retainCpu    — standalone export keeps CPU f32 copies of x/y so hover can
//                  read approximate values with no kernel attached (§37).
//   refreshColor — re-resolve CSS-expressed constant colors on theme change
//                  (§36 live re-resolution); each kind knows where its
//                  constant color lives in the spec.
const MARK_KINDS = {
  scatter: {
    build: (view, g, t, buffer) => view._buildScatterMark(g, t, buffer),
    draw: (view, g, x0, x1, y0, y1) =>
      view._drawPoints(g, view._map(g.xMeta, x0, x1), view._map(g.yMeta, y0, y1)),
    pointPick: true,
    retainCpu: true,
    refreshColor: (view, g) => {
      if (g.colorMode === 0 && g.trace.color) {
        g.color = parseColor(view.root, g.trace.color.color, g.color);
      }
    },
  },
  line: {
    build: (view, g, t, buffer) => view._buildLineMark(g, t, buffer),
    draw: (view, g, x0, x1, y0, y1) =>
      view._drawLine(g, view._map(g.xMeta, x0, x1), view._map(g.yMeta, y0, y1)),
    refreshColor: (view, g) => {
      g.color = parseColor(view.root, g.trace.style.color, g.color);
    },
  },
  candlestick: {
    build: (view, g, t, buffer) => view._buildCandleMark(g, t, buffer),
    draw: (view, g, x0, x1, y0, y1) => view._drawCandles(g, x0, x1, y0, y1),
    // Rect geometry, not a point — hover is a CPU nearest-x readout (§17),
    // handled by ChartView._hover via the `hover` hook rather than GPU pick.
    hover: (view, g, dataX) => view._candleHoverRow(g, dataX),
    refreshColor: (view, g) => {
      g.candle.up = parseColor(view.root, g.trace.style.up_color, g.candle.up);
      g.candle.down = parseColor(view.root, g.trace.style.down_color, g.candle.down);
    },
  },
  // OHLC bars: same OHLC data + build/hover as candlestick, tick-bar geometry.
  ohlc: {
    build: (view, g, t, buffer) => view._buildCandleMark(g, t, buffer),
    draw: (view, g, x0, x1, y0, y1) => view._drawOHLC(g, x0, x1, y0, y1),
    hover: (view, g, dataX) => view._candleHoverRow(g, dataX),
    refreshColor: (view, g) => {
      g.candle.up = parseColor(view.root, g.trace.style.up_color, g.candle.up);
      g.candle.down = parseColor(view.root, g.trace.style.down_color, g.candle.down);
    },
  },
};

// Registry lookup with the scatter fallback every dispatch site shares.
function markOf(kind) {
  return MARK_KINDS[kind] || MARK_KINDS.scatter;
}
// ---------------------------------------------------------------------------
// Entry points
// ---------------------------------------------------------------------------

function bytesToArrayBuffer(b) {
  if (b instanceof ArrayBuffer) return b;
  if (b instanceof DataView || ArrayBuffer.isView(b)) {
    return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
  }
  throw new Error("unsupported buffer type");
}

function render({ model, el }) {
  const spec = model.get("spec");
  const buffer = bytesToArrayBuffer(model.get("buffers"));
  const comm = {
    send: (msg) => model.send(msg),
    onMessage: (cb) => model.on("msg:custom", (content, buffers) => cb(content, buffers)),
  };
  const view = new ChartView(el, spec, buffer, comm);
  return () => view.destroy();
}

/** Standalone (static HTML export — no kernel). Retains CPU f32 copies of
 * scatter x/y so hover can read approximate values without a kernel (§37). */
function renderStandalone(el, spec, arrayBuffer) {
  const buffer = bytesToArrayBuffer(arrayBuffer);
  const view = new ChartView(el, spec, buffer, null);
  for (const g of view.gpuTraces) {
    if (markOf(g.trace.kind).retainCpu && g.tier !== "density") {
      g._cpu = {
        x: new Float32Array(buffer, spec.columns[g.trace.x].byte_offset, spec.columns[g.trace.x].len),
        y: new Float32Array(buffer, spec.columns[g.trace.y].byte_offset, spec.columns[g.trace.y].len),
      };
    }
  }
  return view;
}

// ---- exports ---- (everything below this marker is stripped for the IIFE build)
export { render, renderStandalone, ChartView, MARK_KINDS, markOf };
export default { render };
