/**
 * fastcharts render client — Phase 0.
 *
 * A thin GPU render client (design dossier §32): receives a data-less spec +
 * offset-encoded f32 columns as raw binary (§29 — no JSON numbers, no parse),
 * uploads them once to WebGL2 buffers, and draws with instanced primitives.
 * Pan/zoom is a uniform update — it never touches data buffers (§7). When a
 * zoom outruns the shipped decimation, it asks the kernel to re-decimate the
 * visible window and swaps buffers when the answer arrives, drawing the stale
 * tier until then (§17 stale-while-revalidate).
 *
 * Deliberately dependency-free: this file is the entire client. DOM is used
 * only for chrome — title, axis tick labels, legend (§7).
 */

"use strict";

// ---------------------------------------------------------------------------
// Colors & theming (§36: chrome inherits CSS; marks read --chart-* tokens)
// ---------------------------------------------------------------------------

/** Resolve any CSS color expression to [r,g,b,a] via a probe element —
 * handles oklch(), color-mix(), named colors without a CSS parser (§36b). */
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

/** Theme derived from the container: tokens if set, otherwise the inherited
 * text color at reduced alpha — auto-adapts to light/dark notebooks. */
function readTheme(root) {
  const text = resolveCssColor(root, "currentColor") || [0.2, 0.2, 0.2, 1];
  const withA = (c, a) => [c[0], c[1], c[2], a];
  const tok = (name) => {
    const v = cssToken(root, name);
    return v ? resolveCssColor(root, v) || null : null;
  };
  return {
    bg: tok("--chart-bg"), // null = transparent, page shows through
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
  for (let v = first; v <= hi + step * 1e-9; v += step) {
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
  // Month/year steps need calendar arithmetic (§16: months are not 30×86400s).
  if (rough > 14 * MS.d) {
    return calendarTicks(lo, hi, rough);
  }
  let step = TIME_STEPS[TIME_STEPS.length - 1];
  for (const s of TIME_STEPS) {
    if (s >= rough) { step = s; break; }
  }
  const first = Math.ceil(lo / step) * step;
  const out = [];
  for (let v = first; v <= hi; v += step) out.push(v);
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
  return v.toFixed(Math.min(dec, 8)).replace(/\.?0+$/, "") || "0";
}

// ---------------------------------------------------------------------------
// WebGL2 helpers
// ---------------------------------------------------------------------------

function compile(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    throw new Error("shader compile: " + gl.getShaderInfoLog(sh));
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

// Marks are SDF-shaded quads/sprites — resolution-independent AA (research §4.5).
const POINT_VS = `#version 300 es
in float ax; in float ay;
uniform vec2 u_xmap; uniform vec2 u_ymap; uniform float u_size;
void main() {
  gl_Position = vec4(ax * u_xmap.x + u_xmap.y, ay * u_ymap.x + u_ymap.y, 0.0, 1.0);
  gl_PointSize = u_size;
}`;

const POINT_FS = `#version 300 es
precision mediump float;
uniform vec4 u_color;
out vec4 outColor;
void main() {
  vec2 d = gl_PointCoord - 0.5;
  float r = length(d) * 2.0;
  float aa = fwidth(r) + 1e-4;
  float alpha = (1.0 - smoothstep(1.0 - aa, 1.0, r)) * u_color.a;
  if (alpha <= 0.001) discard;
  outColor = vec4(u_color.rgb * alpha, alpha);
}`;

// Lines: one instanced quad per segment, extruded in pixel space with an
// SDF-antialiased edge. SoA buffers: x0/x1 are the same buffer at a 4-byte
// offset. (Research §4.4 — nobody serious uses GL.LINES.)
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
precision mediump float;
uniform vec4 u_color; uniform float u_width;
in float v_off;
out vec4 outColor;
void main() {
  float half_w = u_width * 0.5;
  float alpha = (1.0 - smoothstep(half_w - 0.5, half_w + 0.5, abs(v_off))) * u_color.a;
  if (alpha <= 0.001) discard;
  outColor = vec4(u_color.rgb * alpha, alpha);
}`;

// ---------------------------------------------------------------------------
// ChartView
// ---------------------------------------------------------------------------

const MARGIN = { l: 62, r: 14, t: 10, b: 42 };

class ChartView {
  /**
   * @param el host element
   * @param spec data-less spec (§9)
   * @param buffer ArrayBuffer of concatenated relative-f32 columns
   * @param comm {send(msg), onMessage(cb)} | null (null = static HTML export)
   */
  constructor(el, spec, buffer, comm) {
    if (spec.protocol !== 1) {
      // §33: version mismatch fails loudly with an upgrade hint, never renders wrong.
      el.textContent =
        `fastcharts: protocol mismatch (client speaks 1, kernel sent ${spec.protocol}). ` +
        "Update the fastcharts package and restart the kernel.";
      throw new Error("protocol mismatch");
    }
    this.spec = spec;
    this.comm = comm;
    this.seq = 0;

    const top = MARGIN.t + (spec.title ? 30 : 0);
    this.plot = {
      x: MARGIN.l,
      y: top,
      w: Math.max(40, spec.width - MARGIN.l - MARGIN.r),
      h: Math.max(40, spec.height - top - MARGIN.b),
    };

    this._buildDom(el);
    this.theme = readTheme(this.root);
    this._initGl(buffer);
    this._initInteraction();

    // Initial view = spec autorange (computed kernel-side from zone maps, §22).
    this.view0 = {
      x0: spec.x_axis.range[0], x1: spec.x_axis.range[1],
      y0: spec.y_axis.range[0], y1: spec.y_axis.range[1],
    };
    this.view = { ...this.view0 };

    this._themeWatch = window.matchMedia("(prefers-color-scheme: dark)");
    this._onScheme = () => this.refreshTheme();
    this._themeWatch.addEventListener?.("change", this._onScheme);

    if (comm) {
      comm.onMessage((msg, buffers) => this._onKernelMsg(msg, buffers));
    }
    this.draw();
  }

  _buildDom(el) {
    const s = this.spec;
    const root = document.createElement("div");
    root.className = "fastcharts";
    root.style.cssText =
      `position:relative;width:${s.width}px;height:${s.height}px;` +
      "font:12px system-ui,sans-serif;user-select:none;";
    el.appendChild(root);
    this.root = root;

    if (s.title) {
      const t = document.createElement("div");
      t.textContent = s.title;
      t.style.cssText =
        "position:absolute;top:6px;left:0;right:0;text-align:center;" +
        "font-size:14px;font-weight:600;";
      root.appendChild(t);
    }

    // Chrome canvas (grid, axes) under the GL canvas; DOM text on top (§7).
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

    const named = s.traces.filter((t) => t.name);
    if (named.length) {
      const lg = document.createElement("div");
      lg.style.cssText =
        `position:absolute;top:${this.plot.y + 6}px;right:${MARGIN.r + 6}px;` +
        "display:flex;flex-direction:column;gap:2px;font-size:11px;" +
        "background:rgba(128,128,128,.08);border-radius:4px;padding:4px 8px;";
      for (const t of named) {
        const row = document.createElement("div");
        const sw = document.createElement("span");
        sw.style.cssText =
          `display:inline-block;width:10px;height:10px;border-radius:5px;` +
          `background:${t.style.color};margin-right:5px;vertical-align:-1px;`;
        row.appendChild(sw);
        row.appendChild(document.createTextNode(t.name));
        lg.appendChild(row);
      }
      root.appendChild(lg);
    }
  }

  _initGl(buffer) {
    const dpr = window.devicePixelRatio || 1;
    this.dpr = dpr;
    this.canvas.width = this.plot.w * dpr;
    this.canvas.height = this.plot.h * dpr;
    this.chrome.width = this.spec.width * dpr;
    this.chrome.height = this.spec.height * dpr;
    this.chrome.style.width = this.spec.width + "px";
    this.chrome.style.height = this.spec.height + "px";

    const gl = this.canvas.getContext("webgl2", {
      antialias: false, // marks self-antialias via SDF
      premultipliedAlpha: true,
      alpha: true,
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

    // Upload once; pan/zoom never re-uploads (§7 retained buffers).
    this.gpuTraces = this.spec.traces.map((t) => {
      const x = this._columnView(buffer, this.spec.columns[t.x]);
      const y = this._columnView(buffer, this.spec.columns[t.y]);
      return {
        trace: t,
        xMeta: { ...this.spec.columns[t.x] },
        yMeta: { ...this.spec.columns[t.y] },
        n: Math.min(x.length, y.length),
        xBuf: this._upload(x),
        yBuf: this._upload(y),
        color: parseColor(this.root, t.style.color, [0.3, 0.47, 0.66, 1]),
      };
    });
  }

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

  // -- drawing --------------------------------------------------------------

  /** Column-space → clip-space map. Computed in f64 here; only the small
   * relative values go through f32 (§4 offset encoding). */
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
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    const bg = this.theme.bg;
    if (bg) gl.clearColor(bg[0] * bg[3], bg[1] * bg[3], bg[2] * bg[3], bg[3]);
    else gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);

    for (const g of this.gpuTraces) {
      const xm = this._map(g.xMeta, x0, x1);
      const ym = this._map(g.yMeta, y0, y1);
      if (g.trace.kind === "scatter") {
        this._drawPoints(g, xm, ym);
      } else {
        this._drawLine(g, xm, ym);
      }
    }
    this._drawChrome();
  }

  _drawPoints(g, xm, ym) {
    const gl = this.gl;
    gl.useProgram(this.pointProg);
    const u = (n) => gl.getUniformLocation(this.pointProg, n);
    gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
    gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
    gl.uniform1f(u("u_size"), (g.trace.style.size || 4) * this.dpr);
    const [r, gr, b, a] = g.color;
    gl.uniform4f(u("u_color"), r, gr, b, a * (g.trace.style.opacity ?? 1));
    this._bindScalarAttr(this.pointProg, "ax", g.xBuf, 0, 0);
    this._bindScalarAttr(this.pointProg, "ay", g.yBuf, 0, 0);
    gl.drawArrays(gl.POINTS, 0, g.n);
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
    const [r, gr, b, a] = g.color;
    gl.uniform4f(u("u_color"), r, gr, b, a * (g.trace.style.opacity ?? 1));
    // Same SoA buffer bound twice at a 4-byte offset = segment endpoints.
    this._bindScalarAttr(this.lineProg, "ax0", g.xBuf, 0, 1);
    this._bindScalarAttr(this.lineProg, "ax1", g.xBuf, 4, 1);
    this._bindScalarAttr(this.lineProg, "ay0", g.yBuf, 0, 1);
    this._bindScalarAttr(this.lineProg, "ay1", g.yBuf, 4, 1);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n - 1);
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

  _drawChrome() {
    const s = this.spec;
    const dpr = this.dpr;
    const ctx = this.chrome.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, s.width, s.height);
    this.labels.textContent = "";

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

    // Tick labels are DOM text — crisp, selectable, a11y-visible (§7/§20).
    const label = (text, css) => {
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
      label(fmtLinear(v, yt.step), `right:${s.width - p.x + 8}px;top:${py}px;transform:translateY(-50%);`);
    }
    if (s.x_axis.label) {
      label(s.x_axis.label, `left:${p.x + p.w / 2}px;top:${p.y + p.h + 24}px;transform:translateX(-50%);font-weight:500;`);
    }
    if (s.y_axis.label) {
      label(s.y_axis.label,
        `left:10px;top:${p.y + p.h / 2}px;transform:rotate(-90deg) translateX(50%);transform-origin:left;font-weight:500;`);
    }
  }

  // -- interaction (§17: view changes are same-frame uniform updates) --------

  _initInteraction() {
    const c = this.canvas;
    let drag = null;

    c.addEventListener("pointerdown", (e) => {
      drag = { px: e.clientX, py: e.clientY, view: { ...this.view } };
      c.setPointerCapture(e.pointerId);
    });
    c.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const { x0, x1, y0, y1 } = drag.view;
      const dx = ((e.clientX - drag.px) / this.plot.w) * (x1 - x0);
      const dy = ((e.clientY - drag.py) / this.plot.h) * (y1 - y0);
      this.view = { x0: x0 - dx, x1: x1 - dx, y0: y0 + dy, y1: y1 + dy };
      this.draw();
      this._scheduleViewRequest();
    });
    const end = () => { drag = null; };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);

    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      const f = Math.pow(1.0015, e.deltaY);
      const r = c.getBoundingClientRect();
      const fx = (e.clientX - r.left) / r.width;
      const fy = 1 - (e.clientY - r.top) / r.height;
      const { x0, x1, y0, y1 } = this.view;
      const ax = x0 + fx * (x1 - x0);
      const ay = y0 + fy * (y1 - y0);
      this.view = {
        x0: ax - (ax - x0) * f, x1: ax + (x1 - ax) * f,
        y0: ay - (ay - y0) * f, y1: ay + (y1 - ay) * f,
      };
      this.draw();
      this._scheduleViewRequest();
    }, { passive: false });

    c.addEventListener("dblclick", () => {
      this.view = { ...this.view0 };
      this.draw();
      this._scheduleViewRequest();
    });
  }

  /** Debounced kernel round-trip: re-decimate the visible window (§28).
   * The stale tier keeps drawing under the new view matrix until the swap (§17). */
  _scheduleViewRequest() {
    if (!this.comm || !this.spec.traces.some((t) => t.tier === "decimated")) return;
    clearTimeout(this._viewTimer);
    this._viewTimer = setTimeout(() => {
      this.seq += 1;
      this.comm.send({
        type: "view",
        seq: this.seq,
        x0: this.view.x0,
        x1: this.view.x1,
        px: Math.round(this.plot.w),
      });
    }, 120);
  }

  _onKernelMsg(msg, buffers) {
    if (!msg || msg.type !== "tier_update") return;
    if (msg.seq !== this.seq) return; // superseded request — drop stale answer
    for (const upd of msg.traces) {
      const g = this.gpuTraces.find((t) => t.trace.id === upd.id);
      if (!g) continue;
      const xBytes = buffers[upd.x.buf];
      const yBytes = buffers[upd.y.buf];
      const asF32 = (b) =>
        b instanceof DataView
          ? new Float32Array(b.buffer, b.byteOffset, b.byteLength / 4)
          : new Float32Array(b.buffer || b);
      const gl = this.gl;
      gl.bindBuffer(gl.ARRAY_BUFFER, g.xBuf);
      gl.bufferData(gl.ARRAY_BUFFER, asF32(xBytes), gl.STATIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, g.yBuf);
      gl.bufferData(gl.ARRAY_BUFFER, asF32(yBytes), gl.STATIC_DRAW);
      g.xMeta = { ...g.xMeta, offset: upd.x.offset, scale: upd.x.scale };
      g.yMeta = { ...g.yMeta, offset: upd.y.offset, scale: upd.y.scale };
      g.n = Math.min(upd.x.len, upd.y.len);
    }
    this.draw();
  }

  /** §36 escape hatch: re-resolve theme tokens (called on scheme change too). */
  refreshTheme() {
    this.theme = readTheme(this.root);
    for (const g of this.gpuTraces) {
      g.color = parseColor(this.root, g.trace.style.color, g.color);
    }
    this.draw();
  }

  destroy() {
    this._themeWatch?.removeEventListener?.("change", this._onScheme);
    clearTimeout(this._viewTimer);
    if (this._raf) cancelAnimationFrame(this._raf);
    this.root.remove();
  }
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

/** anywidget entry point (§33.3). */
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

/** Standalone entry point (static HTML export — no kernel, no tier updates). */
function renderStandalone(el, spec, arrayBuffer) {
  return new ChartView(el, spec, bytesToArrayBuffer(arrayBuffer), null);
}

// ---- exports ---- (everything below this marker is stripped for the IIFE build)
export { render, renderStandalone, ChartView };
export default { render };
