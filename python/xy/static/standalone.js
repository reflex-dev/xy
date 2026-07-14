(() => {

"use strict";
const PROTOCOL = 3;
const COLORMAP_STOPS = {
binary: [[255, 255, 255], [0, 0, 0]],
gray: [[0, 0, 0], [25, 25, 25], [51, 51, 51], [76, 76, 76], [102, 102, 102], [128, 128, 128], [153, 153, 153], [179, 179, 179], [204, 204, 204], [230, 230, 230], [255, 255, 255]],
viridis: [[68, 1, 84], [72, 36, 117], [65, 68, 135], [53, 95, 141], [42, 120, 142], [33, 145, 140], [34, 168, 132], [68, 191, 112], [122, 209, 81], [189, 223, 38], [253, 231, 37]],
plasma: [[13, 8, 135], [65, 4, 157], [106, 0, 168], [143, 13, 164], [177, 42, 144], [204, 71, 120], [225, 100, 98], [242, 132, 75], [252, 166, 54], [252, 206, 37], [240, 249, 33]],
inferno: [[0, 0, 4], [22, 11, 57], [66, 10, 104], [106, 23, 110], [147, 38, 103], [188, 55, 84], [221, 81, 58], [243, 120, 25], [252, 165, 10], [246, 215, 70], [252, 255, 164]],
magma: [[0, 0, 4], [20, 14, 54], [59, 15, 112], [100, 26, 128], [140, 41, 129], [183, 55, 121], [222, 73, 104], [247, 112, 92], [254, 159, 109], [254, 207, 146], [252, 253, 191]],
cividis: [[0, 34, 78], [8, 51, 112], [53, 69, 108], [79, 87, 108], [102, 105, 112], [125, 124, 120], [148, 142, 119], [174, 163, 113], [200, 184, 102], [229, 207, 82], [254, 232, 56]],
coolwarm: [[59, 76, 192], [89, 119, 227], [123, 159, 249], [158, 190, 255], [192, 212, 245], [221, 220, 220], [242, 203, 183], [247, 172, 142], [238, 132, 104], [214, 82, 68], [180, 4, 38]],
turbo: [[48, 18, 59], [69, 89, 203], [62, 155, 254], [25, 213, 205], [70, 248, 132], [164, 252, 60], [225, 221, 55], [254, 164, 49], [240, 91, 18], [195, 37, 3], [122, 4, 3]],
rainbow: [[128, 0, 255], [78, 77, 252], [25, 150, 243], [24, 205, 228], [77, 243, 206], [128, 255, 180], [178, 243, 150], [230, 205, 115], [255, 150, 79], [255, 77, 39], [255, 0, 0]],
jet: [[0, 0, 128], [0, 0, 241], [0, 76, 255], [0, 176, 255], [41, 255, 206], [125, 255, 122], [206, 255, 41], [255, 196, 0], [255, 104, 0], [241, 8, 0], [128, 0, 0]],
rdgy: [[103, 0, 31], [177, 24, 43], [214, 96, 77], [243, 164, 129], [253, 219, 199], [254, 254, 254], [224, 224, 224], [185, 185, 185], [135, 135, 135], [76, 76, 76], [26, 26, 26]],
rdbu: [[103, 0, 31], [177, 24, 43], [214, 96, 77], [243, 164, 129], [253, 219, 199], [246, 247, 247], [209, 229, 240], [144, 196, 221], [67, 147, 195], [32, 101, 171], [5, 48, 97]],
blues: [[247, 251, 255], [227, 238, 249], [208, 225, 242], [183, 212, 234], [148, 196, 223], [106, 174, 214], [74, 152, 201], [46, 126, 188], [23, 100, 171], [8, 74, 145], [8, 48, 107]],
purples: [[252, 251, 253], [242, 240, 247], [226, 226, 239], [206, 207, 229], [182, 182, 216], [158, 154, 200], [134, 131, 189], [114, 98, 172], [97, 64, 155], [79, 31, 139], [63, 0, 125]],
pubu: [[255, 247, 251], [240, 234, 244], [219, 218, 235], [192, 201, 226], [156, 185, 217], [115, 169, 207], [66, 149, 195], [24, 124, 182], [5, 103, 162], [4, 83, 130], [2, 56, 88]],
piyg: [[142, 1, 82], [196, 26, 124], [222, 119, 174], [241, 181, 217], [253, 224, 239], [247, 247, 246], [230, 245, 208], [183, 224, 133], [127, 188, 65], [76, 145, 33], [39, 100, 25]],
prgn: [[64, 0, 75], [117, 41, 130], [153, 112, 171], [193, 164, 206], [231, 212, 232], [246, 247, 246], [217, 240, 211], [165, 218, 159], [90, 174, 97], [26, 119, 54], [0, 68, 27]],
rdylgn: [[165, 0, 38], [214, 47, 39], [244, 109, 67], [253, 173, 96], [254, 224, 139], [254, 255, 190], [217, 239, 139], [165, 216, 106], [102, 189, 99], [25, 151, 80], [0, 104, 55]],
spectral: [[158, 1, 66], [212, 61, 79], [244, 109, 67], [253, 173, 96], [254, 224, 139], [255, 255, 190], [230, 245, 152], [170, 220, 164], [102, 194, 165], [51, 135, 188], [94, 79, 162]],
};
function colormapStops(name) {
const reversed = typeof name === "string" && name.endsWith("_r");
const base = reversed ? name.slice(0, -2) : name;
const stops = COLORMAP_STOPS[base] || COLORMAP_STOPS.viridis;
return reversed ? [...stops].reverse() : stops;
}
function buildLutData(name) {
const stops = colormapStops(name);
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
if (!/^(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(h)) {
return null;
}
const full = h.length === 3 || h.length === 4 ? [...h].map((c) => c + c).join("") : h;
const n = parseInt(full.slice(0, 6), 16);
const a = full.length === 8 ? parseInt(full.slice(6, 8), 16) / 255 : 1;
return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255, a];
}
function parseColor(host, c, fallback) {
if (!c) return fallback;
if (typeof c !== "string") return fallback;
const expr = c.trim();
if (!expr) return fallback;
const out = expr.startsWith("#") ? hexColor(expr) : resolveCssColor(host, expr);
if (out) return out;
if (typeof console !== "undefined" && console.warn) {
console.warn(`xy: unresolvable color ${JSON.stringify(expr)}; using fallback`);
}
return fallback;
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
const FC_CHROME_CSS = `
:where(.xy [data-fc-slot="title"]){text-align:center;font-size:14px;font-weight:600;color:var(--chart-text,inherit)}
:where(.xy [data-fc-slot="tooltip"]){background:var(--chart-tooltip-bg,rgba(20,24,33,.92));color:var(--chart-tooltip-text,#fff);padding:5px 8px;border-radius:4px;font-size:11px;line-height:1.35;box-shadow:0 2px 8px rgba(0,0,0,.3)}
:where(.xy [data-fc-slot="legend"]){gap:2px;font-size:11px;background:var(--chart-legend-bg,rgba(128,128,128,.08));border-radius:4px;padding:4px 8px;color:var(--chart-text,inherit)}
:where(.xy [data-fc-slot="legend_swatch"]){width:12px;height:10px;border-radius:2px;margin-right:5px}
:where(.xy [data-fc-slot="badge"]){gap:3px;font-size:11px;line-height:1.2}
:where(.xy [data-fc-slot="badge_item"]){padding:3px 6px;border-radius:4px;color:var(--chart-badge-text,#0f172a);background:var(--chart-badge-bg,rgba(255,255,255,.82));box-shadow:0 1px 4px rgba(15,23,42,.14)}
:where(.xy [data-fc-slot="modebar"]){gap:1px;background:var(--chart-modebar-bg,rgba(255,255,255,.78));border:1px solid rgba(128,128,128,.18);border-radius:4px;padding:1px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
:where(.xy [data-fc-slot="modebar_button"]){width:26px;height:24px;padding:0;border:none;background:transparent;border-radius:3px;color:var(--chart-axis,currentColor);cursor:pointer}
:where(.xy [data-fc-slot="modebar_button"].fc-active){background:var(--chart-modebar-active,rgba(128,128,128,.22))}
:where(.xy [data-fc-slot="selection"]){border:1px solid var(--chart-selection,rgba(90,140,240,.9));background:var(--chart-selection-fill,rgba(90,140,240,.15))}
:where(.xy [data-fc-slot="crosshair_x"],.xy [data-fc-slot="crosshair_y"]){background:var(--chart-crosshair,rgba(15,23,42,.42))}
:where(.xy [data-fc-slot="tick_label"]){color:var(--chart-text,inherit)}
:where(.xy [data-fc-slot="axis_title"]){color:var(--chart-text,inherit);font-size:12px}
:where(.xy [data-fc-slot="annotation_label"]){font-size:11px;line-height:1.2;font-weight:500;color:var(--chart-annotation-text,var(--chart-text,inherit))}
:where(.xy [data-fc-slot="canvas"]){cursor:var(--chart-cursor,crosshair)}
:where(.xy [data-fc-slot="canvas"][data-fc-dragmode="pan"]){cursor:var(--chart-cursor-pan,grab)}
`;
function ensureChromeStylesheet(node) {
let root = node && node.getRootNode ? node.getRootNode() : document;
const isShadow = typeof ShadowRoot !== "undefined" && root instanceof ShadowRoot;
if (!isShadow && !(root instanceof Document)) root = document;
const scope = isShadow ? root : (root.head || document.head || root.documentElement);
if (!scope || !scope.querySelector) return;
if (scope.querySelector("style[data-xy-chrome]")) return;
const style = document.createElement("style");
style.setAttribute("data-xy-chrome", "");
style.textContent = FC_CHROME_CSS;
scope.appendChild(style);
}
function safeCssPaint(host, expr, fallback = [0.5, 0.5, 0.5, 1]) {
const parsed = parseColor(host, expr, fallback);
const color = Array.isArray(parsed) && parsed.length >= 4 && parsed.every(Number.isFinite)
? parsed
: fallback;
return cssColor(color);
}
function niceStep(rough) {
rough = Math.abs(rough);
if (!Number.isFinite(rough) || rough <= 0) return 1;
const mag = Math.pow(10, Math.floor(Math.log10(rough)));
for (const m of [1, 2, 2.5, 5, 10]) {
if (rough <= m * mag * (1 + 1e-12)) return m * mag;
}
return 10 * mag;
}
function linearTicks(lo, hi, target = 6) {
if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { ticks: [], step: 1 };
const a = Math.min(lo, hi);
const b = Math.max(lo, hi);
if (a === b) return { ticks: [a], step: 1 };
const step = niceStep((b - a) / target);
const first = Math.ceil(a / step) * step;
const out = [];
for (let v = first; v <= b + step * 1e-9 && out.length < 200; v += step) {
out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
}
return { ticks: out, step };
}
function logTicks(lo, hi, target = 6) {
if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { ticks: [], step: 1 };
const a = Math.min(lo, hi);
const b = Math.max(lo, hi);
if (a <= 0 || b <= 0) return { ticks: [], step: 1 };
const e0 = Math.floor(Math.log10(a));
const e1 = Math.ceil(Math.log10(b));
const span = Math.max(1, e1 - e0);
const mults = span <= Math.max(2, target) ? [1, 2, 5] : [1];
const out = [];
const labels = [];
const labelEvery = Math.max(1, Math.ceil((e1 - e0 + 1) / Math.max(1, target)));
for (let e = e0; e <= e1 && out.length < 200; e++) {
const base = Math.pow(10, e);
for (const m of mults) {
const v = m * base;
if (v >= a * (1 - 1e-12) && v <= b * (1 + 1e-12)) {
out.push(v);
if (m === 1 && (e - e0) % labelEvery === 0) labels.push(v);
}
if (out.length >= 200) break;
}
}
return { ticks: out, labels: labels.length ? labels : out, step: 1, log: true };
}
function categoryTicks(lo, hi, categories, target = 6) {
if (!categories || !categories.length) return { ticks: [], step: 1 };
const start = Math.max(0, Math.ceil(Math.min(lo, hi)));
const stop = Math.min(categories.length - 1, Math.floor(Math.max(lo, hi)));
if (stop < start) return { ticks: [], step: 1 };
const visible = stop - start + 1;
const step = Math.max(1, Math.ceil(visible / Math.max(1, target)));
const out = [];
for (let v = start; v <= stop && out.length < 200; v += step) out.push(v);
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
if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { ticks: [], step: MS.d };
const a = Math.min(lo, hi);
const b = Math.max(lo, hi);
const span = b - a;
const rough = span / target;
if (rough > 14 * MS.d) return calendarTicks(a, b, rough);
let step = TIME_STEPS[TIME_STEPS.length - 1];
for (const s of TIME_STEPS) {
if (s >= rough) { step = s; break; }
}
const first = Math.ceil(a / step) * step;
const out = [];
for (let v = first; v <= b && out.length < 200; v += step) out.push(v);
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
const av = Math.abs(v);
if (av >= 1e6 || (av !== 0 && av < 1e-4)) return v.toExponential(1).replace("e+", "e");
let dec = step ? Math.max(0, Math.ceil(-Math.log10(Math.abs(step)))) : 0;
while (dec < 8 && Math.abs(Number(step.toFixed(dec)) - step) > Math.abs(step) / 1000) dec++;
return v.toFixed(Math.min(dec, 8));
}
function fmtCategory(v, categories) {
const i = Math.round(v);
return i >= 0 && i < categories.length ? String(categories[i]) : "";
}
function fmtNumberSpec(v, format) {
if (typeof format !== "string" || !Number.isFinite(Number(v))) return null;
const percent = format.endsWith("%");
const raw = percent ? format.slice(0, -1) : format;
const match = raw.match(/^(,)?\.([0-9]+)f?$/);
if (!match) return null;
const digits = Number(match[2]);
const value = percent ? Number(v) * 100 : Number(v);
const text = match[1]
? value.toLocaleString(undefined, {
minimumFractionDigits: digits,
maximumFractionDigits: digits,
})
: value.toFixed(digits);
return percent ? `${text}%` : text;
}
function fmtTimeSpec(ms, format) {
if (typeof format !== "string") return null;
const d = new Date(ms);
if (!Number.isFinite(d.getTime())) return null;
const pad = (n, w = 2) => String(n).padStart(w, "0");
const shortMonth = d.toLocaleString("en", { month: "short", timeZone: "UTC" });
const longMonth = d.toLocaleString("en", { month: "long", timeZone: "UTC" });
return format.replace(/%[YmdHMSbB]/g, (token) => {
switch (token) {
case "%Y": return String(d.getUTCFullYear());
case "%m": return pad(d.getUTCMonth() + 1);
case "%d": return pad(d.getUTCDate());
case "%H": return pad(d.getUTCHours());
case "%M": return pad(d.getUTCMinutes());
case "%S": return pad(d.getUTCSeconds());
case "%b": return shortMonth;
case "%B": return longMonth;
default: return token;
}
});
}
function fmtAxis(axis, v, tickStep) {
if (axis && axis.kind === "category") return fmtCategory(v, axis.categories || []);
if (axis && axis.kind === "time") return fmtTimeSpec(v, axis.format) || fmtTime(v, tickStep);
const formatted = fmtNumberSpec(v, axis && axis.format);
if (axis && axis.scale === "log" && Number(v) > 0 && Number(v) < 1 && formatted === "0") {
return fmtLinear(v, tickStep);
}
return formatted || fmtLinear(v, tickStep);
}
function fmtValue(v, kind) {
if (kind === "time_ms") {
const d = new Date(v);
return d.toISOString().replace("T", " ").replace(".000Z", "Z");
}
if (typeof v === "string") return v;
const n = Number(v);
if (!Number.isFinite(n)) return String(v);
if (n === 0) return "0";
const av = Math.abs(n);
if (av >= 1e6 || av < 1e-4) return n.toExponential(3);
return (Math.round(n * 1e4) / 1e4).toString();
}
function compile(gl, type, src) {
const sh = gl.createShader(type);
gl.shaderSource(sh, src);
gl.compileShader(sh);
if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
throw new Error("shader compile: " + gl.getShaderInfoLog(sh) + "\n" + src);
}
return sh;
}
const ATTR_SLOTS = {
ax: 0, ay: 1,
ax0: 0, ax1: 1, ay0: 2, ay1: 3, ax2: 4, ay2: 5, ab0: 4, ab1: 5,
a_pos: 0, a_v1: 1, a_v0: 2,
a_corner: 0,
a_cval: 6, a_sval: 7, a_sel: 8, a_dval: 9,
a_len0: 10, a_len1: 11,
};
function makeProgram(gl, vs, fs) {
const p = gl.createProgram();
const vsh = compile(gl, gl.VERTEX_SHADER, vs);
const fsh = compile(gl, gl.FRAGMENT_SHADER, fs);
gl.attachShader(p, vsh);
gl.attachShader(p, fsh);
for (const [name, slot] of Object.entries(ATTR_SLOTS)) {
gl.bindAttribLocation(p, slot, name);
}
gl.linkProgram(p);
const ok = gl.getProgramParameter(p, gl.LINK_STATUS);
const info = gl.getProgramInfoLog(p);
gl.detachShader(p, vsh);
gl.detachShader(p, fsh);
gl.deleteShader(vsh);
gl.deleteShader(fsh);
if (!ok) {
gl.deleteProgram(p);
throw new Error("program link: " + info);
}
p._u = Object.create(null);
return p;
}
function uniformOf(gl, prog, name) {
let loc = prog._u[name];
if (loc === undefined) {
loc = gl.getUniformLocation(prog, name);
prog._u[name] = loc;
}
return loc;
}
const AXIS_GLSL = `
float fcDecode(float encoded, vec2 meta) {
  return encoded / max(abs(meta.y), 1e-30) + meta.x;
}
float fcAxisCoord(float encoded, vec2 meta, int mode) {
  float value = fcDecode(encoded, meta);
  if (mode == 1) return value > 0.0 ? log(value) / log(10.0) : -1e30;
  return value;
}
float fcMap(float encoded, vec2 map, vec2 meta, int mode) {
  return fcAxisCoord(encoded, meta, mode) * map.x + map.y;
}
float fcViewCoord(float value, int mode) {
  if (mode == 1) return value > 0.0 ? log(value) / log(10.0) : -1e30;
  return value;
}
float fcViewValue(float coord, int mode) {
  if (mode == 1) return pow(10.0, coord);
  return coord;
}
`;
const POINT_VS = `#version 300 es
in float ax; in float ay; in float a_cval; in float a_sval; in float a_sel; in float a_dval;
uniform vec2 u_xmap; uniform vec2 u_ymap;
uniform vec2 u_xmeta; uniform vec2 u_ymeta; uniform int u_xmode; uniform int u_ymode;
uniform float u_size; uniform int u_sizeMode; uniform vec2 u_sizeRange;
uniform int u_colorMode; uniform float u_dpr; uniform int u_selActive;
uniform float u_selectedOpacity; uniform float u_unselectedOpacity;
out float v_lutCoord; out float v_dim; out float v_dval; out float v_ptSize; out float v_sel;
${AXIS_GLSL}
void main() {
  gl_Position = vec4(fcMap(ax, u_xmap, u_xmeta, u_xmode), fcMap(ay, u_ymap, u_ymeta, u_ymode), 0.0, 1.0);
  float sz = u_sizeMode == 1 ? mix(u_sizeRange.x, u_sizeRange.y, a_sval) : u_size;
  gl_PointSize = sz * u_dpr;
  v_ptSize = sz * u_dpr;
  v_sel = a_sel;
  // continuous: coord = value in [0,1]; categorical: center of texel a_cval.
  v_lutCoord = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
  // Local log-density LUT coord (drill handoff, §5): lets freshly drilled
  // points wear the density colormap so the texture->points swap is seamless.
  v_dval = a_dval;
  // Unselected marks dim when a selection is active (§34 selected/unselected styling).
  v_dim = u_selActive == 1 ? mix(u_unselectedOpacity, u_selectedOpacity, step(0.5, a_sel)) : 1.0;
}`;
const MARKER_SDF_GLSL = `
float fcSegmentDistance(vec2 p, vec2 a, vec2 b) {
  vec2 e = b - a;
  return length(p - a - e * clamp(dot(p - a, e) / dot(e, e), 0.0, 1.0));
}
float fcTriangleDistance(vec2 p, vec2 a, vec2 b, vec2 c) {
  float dist = min(fcSegmentDistance(p, a, b),
                   min(fcSegmentDistance(p, b, c), fcSegmentDistance(p, c, a)));
  float c0 = (b.x-a.x)*(p.y-a.y) - (b.y-a.y)*(p.x-a.x);
  float c1 = (c.x-b.x)*(p.y-b.y) - (c.y-b.y)*(p.x-b.x);
  float c2 = (a.x-c.x)*(p.y-c.y) - (a.y-c.y)*(p.x-c.x);
  bool inside = (c0 >= 0.0 && c1 >= 0.0 && c2 >= 0.0) ||
                (c0 <= 0.0 && c1 <= 0.0 && c2 <= 0.0);
  return inside ? -dist : dist;
}
float fcPentagonDistance(vec2 p) {
  // Path.unit_regular_polygon(5), then Matplotlib's 0.5 marker transform.
  vec2 a = vec2(0.0, -0.5);
  vec2 b = vec2(-0.475528258, -0.154508497);
  vec2 c = vec2(-0.293892626, 0.404508497);
  vec2 d = vec2(0.293892626, 0.404508497);
  vec2 e = vec2(0.475528258, -0.154508497);
  float dist = min(min(fcSegmentDistance(p, a, b), fcSegmentDistance(p, b, c)),
                   min(min(fcSegmentDistance(p, c, d), fcSegmentDistance(p, d, e)),
                       fcSegmentDistance(p, e, a)));
  float c0 = (b.x-a.x)*(p.y-a.y) - (b.y-a.y)*(p.x-a.x);
  float c1 = (c.x-b.x)*(p.y-b.y) - (c.y-b.y)*(p.x-b.x);
  float c2 = (d.x-c.x)*(p.y-c.y) - (d.y-c.y)*(p.x-c.x);
  float c3 = (e.x-d.x)*(p.y-d.y) - (e.y-d.y)*(p.x-d.x);
  float c4 = (a.x-e.x)*(p.y-e.y) - (a.y-e.y)*(p.x-e.x);
  bool inside = (c0 >= 0.0 && c1 >= 0.0 && c2 >= 0.0 && c3 >= 0.0 && c4 >= 0.0) ||
                (c0 <= 0.0 && c1 <= 0.0 && c2 <= 0.0 && c3 <= 0.0 && c4 <= 0.0);
  return inside ? -dist : dist;
}
float fcMarkerSdf(vec2 d, int shape) {
  if (shape == 1) return max(abs(d.x), abs(d.y)) - 0.5;              // square
  if (shape == 2) return (abs(d.x) + abs(d.y)) - 0.5;               // diamond
  if (shape == 4) {                                                 // cross / plus
    vec2 a = abs(d);
    return min(max(a.x - 0.17, a.y - 0.5), max(a.x - 0.5, a.y - 0.17));
  }
  if (shape == 5) {                                                 // regular hexagon (pointy top)
    const vec3 k = vec3(-0.866025404, 0.5, 0.577350269);
    vec2 p = abs(vec2(d.y, d.x));
    p -= 2.0 * min(dot(k.xy, p), 0.0) * k.xy;
    p -= vec2(clamp(p.x, -k.z * 0.5, k.z * 0.5), 0.5);
    return length(p) * sign(p.y);
  }
  if (shape == 6) return fcPentagonDistance(d);                      // exact regular pentagon
  if (shape == 7) {                                                 // five-pointed star (apex up)
    const float rf = 0.45;
    const vec2 k1 = vec2(0.809016994, -0.587785252);
    const vec2 k2 = vec2(-k1.x, k1.y);
    vec2 p = vec2(abs(d.x), -d.y);
    p -= 2.0 * max(dot(k1, p), 0.0) * k1;
    p -= 2.0 * max(dot(k2, p), 0.0) * k2;
    p = vec2(abs(p.x), p.y - 0.5);
    vec2 ba = rf * vec2(-k1.y, k1.x) - vec2(0.0, 1.0);
    float h = clamp(dot(p, ba) / dot(ba, ba), 0.0, 0.5);
    return length(p - ba * h) * sign(p.y * ba.x - p.x * ba.y);
  }
  if (shape == 3 || shape == 8 || shape == 9 || shape == 10) {     // Matplotlib triangle path
    vec2 q = d;
    if (shape == 8) q = -d;
    if (shape == 9) q = vec2(d.y, -d.x);
    if (shape == 10) q = vec2(-d.y, d.x);
    return fcTriangleDistance(q, vec2(0.0, -0.5), vec2(-0.5, 0.5), vec2(0.5, 0.5));
  }
  if (shape == 11) {                                                // diagonal x
    vec2 q = vec2(d.x + d.y, d.y - d.x) * 0.707106781;
    vec2 a = abs(q);
    return min(max(a.x - 0.17, a.y - 0.5), max(a.x - 0.5, a.y - 0.17));
  }
  if (shape == 13) return max(abs(d.x), abs(d.y)) - 0.5;            // snapped pixel
  if (shape == 14) return (abs(d.x) / 0.6 + abs(d.y)) - 0.5;        // thin diamond
  return length(d) - 0.5;                                           // circle
}`;
const POINT_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_color; uniform int u_colorMode; uniform sampler2D u_lut; uniform float u_opacity;
uniform sampler2D u_dlut; uniform float u_dblend;
uniform int u_symbol; uniform vec4 u_ptStroke; uniform float u_ptStrokeWidth;
uniform int u_selActive; uniform vec4 u_selColor; uniform vec4 u_unselColor;
in float v_lutCoord; in float v_dim; in float v_dval; in float v_ptSize; in float v_sel;
out vec4 outColor;
${MARKER_SDF_GLSL}
void main() {
  vec2 d = gl_PointCoord - 0.5;
  float sd;
  bool lineMarker = u_symbol == 15 || u_symbol == 16;
  if (lineMarker) {
    vec2 q = u_symbol == 16 ? vec2(d.x + d.y, d.y - d.x) * 0.707106781 : d;
    float halfWidth = max(u_ptStrokeWidth, 1.0) / (2.0 * max(v_ptSize, 1.0));
    vec2 a = abs(q);
    sd = min(max(a.x - 0.5, a.y - halfWidth), max(a.y - 0.5, a.x - halfWidth));
  } else {
    sd = fcMarkerSdf(d, u_symbol);
  }
  float aa = fwidth(sd) + 1e-4;
  float shapeCov = clamp(0.5 - sd / aa, 0.0, 1.0);
  if (shapeCov <= 0.001) discard;
  vec3 rgb = u_colorMode == 0 ? u_color.rgb : texture(u_lut, vec2(clamp(v_lutCoord, 0.0, 1.0), 0.5)).rgb;
  // Drill handoff (§5): near the density boundary, paint by local density with
  // the density ramp; ease into native colors as the zoom deepens (u_dblend->0).
  if (u_dblend > 0.001) {
    vec3 drgb = texture(u_dlut, vec2(clamp(v_dval, 0.0, 1.0), 0.5)).rgb;
    rgb = mix(rgb, drgb, u_dblend);
  }
  // §34 selected/unselected recolor: when a selection is active, tint each point
  // toward its state color (.a is the mix weight; 0 = keep native color).
  if (u_selActive == 1) {
    vec4 sc = v_sel > 0.5 ? u_selColor : u_unselColor;
    rgb = mix(rgb, sc.rgb, sc.a);
  }
  float fillAlpha = u_opacity;
  vec4 px = vec4(rgb * fillAlpha, fillAlpha);   // premultiplied fill
  if (u_ptStrokeWidth > 0.0 && !lineMarker) {
    float sw = u_ptStrokeWidth / max(v_ptSize, 1.0);   // px -> gl_PointCoord units
    float innerCov = clamp(0.5 - (sd + sw) / aa, 0.0, 1.0);
    px = mix(u_ptStroke, px, innerCov);                // ring = stroke, inside = fill
  }
  outColor = px * (shapeCov * v_dim);
}`;
const POINT_SIMPLE_VS = `#version 300 es
in float ax; in float ay;
uniform vec2 u_xmap; uniform vec2 u_ymap;
uniform vec2 u_xmeta; uniform vec2 u_ymeta; uniform int u_xmode; uniform int u_ymode;
uniform float u_size; uniform float u_dpr;
${AXIS_GLSL}
void main() {
  gl_Position = vec4(fcMap(ax, u_xmap, u_xmeta, u_xmode), fcMap(ay, u_ymap, u_ymeta, u_ymode), 0.0, 1.0);
  gl_PointSize = u_size * u_dpr;
}`;
const POINT_SIMPLE_FS = `#version 300 es
precision highp float;
uniform vec4 u_color;
out vec4 outColor;
void main() {
  float sd = length(gl_PointCoord - 0.5) - 0.5;
  float aa = fwidth(sd) + 1e-4;
  float coverage = clamp(0.5 - sd / aa, 0.0, 1.0);
  if (coverage <= 0.001) discard;
  outColor = vec4(u_color.rgb * u_color.a, u_color.a) * coverage;
}`;
const PICK_VS = `#version 300 es
in float ax; in float ay; in float a_sval;
uniform vec2 u_xmap; uniform vec2 u_ymap;
uniform vec2 u_xmeta; uniform vec2 u_ymeta; uniform int u_xmode; uniform int u_ymode;
uniform float u_size; uniform int u_sizeMode; uniform vec2 u_sizeRange; uniform float u_dpr;
flat out int v_id;
${AXIS_GLSL}
void main() {
  gl_Position = vec4(fcMap(ax, u_xmap, u_xmeta, u_xmode), fcMap(ay, u_ymap, u_ymeta, u_ymode), 0.0, 1.0);
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
const GRID_VS = `#version 300 es
in vec2 a_corner;
uniform vec4 u_view; // x0,x1,y0,y1
uniform int u_xmode; uniform int u_ymode;
out vec2 v_data;
${AXIS_GLSL}
void main() {
  gl_Position = vec4(a_corner * 2.0 - 1.0, 0.0, 1.0);
  float x = mix(fcViewCoord(u_view.x, u_xmode), fcViewCoord(u_view.y, u_xmode), a_corner.x);
  float y = mix(fcViewCoord(u_view.z, u_ymode), fcViewCoord(u_view.w, u_ymode), a_corner.y);
  v_data = vec2(fcViewValue(x, u_xmode), fcViewValue(y, u_ymode));
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
const HEATMAP_FS = `#version 300 es
precision highp float;
uniform sampler2D u_grid; uniform sampler2D u_lut;
uniform vec4 u_gridRange; // gx0,gx1,gy0,gy1
uniform float u_opacity;
uniform int u_truecolor;
in vec2 v_data;
out vec4 outColor;
void main() {
  vec2 uv = vec2((v_data.x - u_gridRange.x) / (u_gridRange.y - u_gridRange.x),
                 (v_data.y - u_gridRange.z) / (u_gridRange.w - u_gridRange.z));
  if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) discard;
  vec4 sampled = texture(u_grid, uv);
  if (u_truecolor == 1) {
    float alpha = sampled.a * u_opacity;
    if (alpha <= 0.0) discard;
    outColor = vec4(sampled.rgb * alpha, alpha);
    return;
  }
  float raw = sampled.r;
  if (raw <= 0.0) discard;
  float t = clamp((raw * 255.0 - 1.0) / 254.0, 0.0, 1.0);
  vec3 rgb = texture(u_lut, vec2(t, 0.5)).rgb;
  outColor = vec4(rgb * u_opacity, u_opacity);
}`;
const LINE_VS = `#version 300 es
in float ax0; in float ay0; in float ax1; in float ay1;
uniform vec2 u_xmap; uniform vec2 u_ymap; uniform vec2 u_res; uniform float u_width;
uniform int u_colorMode;
uniform vec2 u_xmeta; uniform vec2 u_ymeta; uniform int u_xmode; uniform int u_ymode;
in float a_len0; in float a_len1;
out float v_off; out float v_dash;
const vec2 corners[4] = vec2[4](vec2(0.,-1.), vec2(0.,1.), vec2(1.,-1.), vec2(1.,1.));
${AXIS_GLSL}
void main() {
  vec2 p0 = vec2(fcMap(ax0, u_xmap, u_xmeta, u_xmode), fcMap(ay0, u_ymap, u_ymeta, u_ymode));
  vec2 p1 = vec2(fcMap(ax1, u_xmap, u_xmeta, u_xmode), fcMap(ay1, u_ymap, u_ymeta, u_ymode));
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
  // Cumulative screen-space arc length at this fragment (device px), fed from
  // CPU-computed per-vertex lengths so dashes stay continuous across segments
  // and constant on screen through zoom.
  v_dash = mix(a_len0, a_len1, c.x);
}`;
const LINE_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_color; uniform float u_width;
uniform int u_dashCount; uniform float u_dashArr[8]; uniform float u_dashPeriod;
in float v_off; in float v_dash;
out vec4 outColor;
void main() {
  float half_w = u_width * 0.5;
  float alpha = (1.0 - smoothstep(half_w - 0.5, half_w + 0.5, abs(v_off))) * u_color.a;
  if (u_dashCount > 0) {
    float m = mod(v_dash, u_dashPeriod);
    float acc = 0.0;
    float on = 0.0;
    for (int i = 0; i < 8; i++) {
      if (i >= u_dashCount) break;
      float next = acc + u_dashArr[i];
      if (m < next) {
        // 0.6px feather at each dash start/end so edges aren't aliased.
        float d = min(m - acc, next - m);
        on = (i % 2 == 0) ? clamp(d + 0.6, 0.0, 1.0) : 1.0 - clamp(d + 0.6, 0.0, 1.0);
        break;
      }
      acc = next;
    }
    alpha *= on;
  }
  if (alpha <= 0.001) discard;
  outColor = vec4(u_color.rgb * alpha, alpha);
}`;
const SEGMENT_VS = `#version 300 es
in float ax0; in float ay0; in float ax1; in float ay1; in float a_cval;
uniform vec2 u_xmap; uniform vec2 u_ymap; uniform vec2 u_res; uniform float u_width;
uniform int u_colorMode;
uniform vec2 u_x0meta; uniform vec2 u_x1meta; uniform vec2 u_y0meta; uniform vec2 u_y1meta;
uniform int u_x0mode; uniform int u_x1mode; uniform int u_y0mode; uniform int u_y1mode;
out float v_off; out float v_cval;
const vec2 corners[4] = vec2[4](vec2(0.,-1.), vec2(0.,1.), vec2(1.,-1.), vec2(1.,1.));
${AXIS_GLSL}
void main() {
  vec2 p0 = vec2(fcMap(ax0, u_xmap, u_x0meta, u_x0mode), fcMap(ay0, u_ymap, u_y0meta, u_y0mode));
  vec2 p1 = vec2(fcMap(ax1, u_xmap, u_x1meta, u_x1mode), fcMap(ay1, u_ymap, u_y1meta, u_y1mode));
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
  v_cval = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
}`;
const SEGMENT_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_color; uniform float u_width; uniform int u_colorMode; uniform sampler2D u_lut;
in float v_off; in float v_cval;
out vec4 outColor;
void main() {
  float half_w = u_width * 0.5;
  vec3 rgb = u_colorMode != 0 ? texture(u_lut, vec2(clamp(v_cval, 0.0, 1.0), 0.5)).rgb : u_color.rgb;
  float alpha = (1.0 - smoothstep(half_w - 0.5, half_w + 0.5, abs(v_off))) * u_color.a;
  if (alpha <= 0.001) discard;
  outColor = vec4(rgb * alpha, alpha);
}`;
const MESH_VS = `#version 300 es
in float ax0; in float ay0; in float ax1; in float ay1; in float ax2; in float ay2; in float a_cval;
uniform vec2 u_xmap; uniform vec2 u_ymap;
uniform vec2 u_x0meta; uniform vec2 u_x1meta; uniform vec2 u_x2meta;
uniform vec2 u_y0meta; uniform vec2 u_y1meta; uniform vec2 u_y2meta;
uniform int u_x0mode; uniform int u_x1mode; uniform int u_x2mode;
uniform int u_y0mode; uniform int u_y1mode; uniform int u_y2mode;
uniform int u_colorMode;
out float v_cval; out vec3 v_bary;
${AXIS_GLSL}
void main() {
  int vertex = gl_VertexID % 3;
  float x = vertex == 0 ? ax0 : (vertex == 1 ? ax1 : ax2);
  float y = vertex == 0 ? ay0 : (vertex == 1 ? ay1 : ay2);
  vec2 xm = vertex == 0 ? u_x0meta : (vertex == 1 ? u_x1meta : u_x2meta);
  vec2 ym = vertex == 0 ? u_y0meta : (vertex == 1 ? u_y1meta : u_y2meta);
  int xmode = vertex == 0 ? u_x0mode : (vertex == 1 ? u_x1mode : u_x2mode);
  int ymode = vertex == 0 ? u_y0mode : (vertex == 1 ? u_y1mode : u_y2mode);
  gl_Position = vec4(fcMap(x, u_xmap, xm, xmode), fcMap(y, u_ymap, ym, ymode), 0.0, 1.0);
  v_cval = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
  v_bary = vertex == 0 ? vec3(1.,0.,0.) : (vertex == 1 ? vec3(0.,1.,0.) : vec3(0.,0.,1.));
}`;
const MESH_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_color; uniform int u_colorMode; uniform sampler2D u_lut; uniform float u_opacity;
uniform vec4 u_stroke; uniform float u_strokeWidth;
in float v_cval; in vec3 v_bary;
out vec4 outColor;
void main() {
  vec3 rgb = u_colorMode == 0 ? u_color.rgb : texture(u_lut, vec2(clamp(v_cval, 0.0, 1.0), 0.5)).rgb;
  vec4 fill = vec4(rgb * u_opacity, u_opacity);
  if (u_strokeWidth > 0.0) {
    float edge = min(v_bary.x, min(v_bary.y, v_bary.z));
    float coverage = smoothstep(0.0, max(fwidth(edge) * u_strokeWidth, 1e-5), edge);
    outColor = mix(u_stroke, fill, coverage);
  } else {
    outColor = fill;
  }
}`;
const GRAD_GLSL = `
uniform int u_gradMode; uniform int u_gradDir; uniform int u_gradCount;
uniform float u_gradPos[8]; uniform vec4 u_gradColor[8];
vec4 fcGradSample(float t) {
  vec4 c0 = u_gradColor[0]; float p0 = u_gradPos[0];
  if (t <= p0) return c0;
  for (int i = 1; i < 8; i++) {
    if (i >= u_gradCount) break;
    float p1 = u_gradPos[i]; vec4 c1 = u_gradColor[i];
    if (t <= p1) return mix(c0, c1, (t - p0) / max(p1 - p0, 1e-6));
    p0 = p1; c0 = c1;
  }
  return c0;
}
float fcGradT(float markT, vec2 res) {
  float t;
  if (u_gradMode == 2) {
    vec2 f = gl_FragCoord.xy / max(res, vec2(1.0));
    t = u_gradDir == 0 ? 1.0 - f.y : u_gradDir == 1 ? f.y : u_gradDir == 2 ? 1.0 - f.x : f.x;
  } else {
    t = u_gradDir == 0 ? 1.0 - markT : markT;
  }
  return clamp(t, 0.0, 1.0);
}`;
const AREA_VS = `#version 300 es
in float ax0; in float ax1; in float ay0; in float ay1; in float ab0; in float ab1;
uniform vec2 u_xmap; uniform vec2 u_ymap; uniform vec2 u_bmap;
uniform vec2 u_xmeta; uniform vec2 u_ymeta; uniform vec2 u_bmeta;
uniform int u_xmode; uniform int u_ymode;
out float v_top; out float v_base; out float v_pos;
const vec2 corners[4] = vec2[4](vec2(0.,0.), vec2(1.,0.), vec2(0.,1.), vec2(1.,1.));
${AXIS_GLSL}
void main() {
  vec2 c = corners[gl_VertexID];
  float x0 = fcMap(ax0, u_xmap, u_xmeta, u_xmode);
  float x1 = fcMap(ax1, u_xmap, u_xmeta, u_xmode);
  float y0 = fcMap(ay0, u_ymap, u_ymeta, u_ymode);
  float y1 = fcMap(ay1, u_ymap, u_ymeta, u_ymode);
  float b0 = fcMap(ab0, u_bmap, u_bmeta, u_ymode);
  float b1 = fcMap(ab1, u_bmap, u_bmeta, u_ymode);
  float top = mix(y0, y1, c.x);
  float base = mix(b0, b1, c.x);
  float clipY = mix(base, top, c.y);
  // Carry the curve top, baseline, and this fragment's Y *separately* (each is
  // linear in x and continuous across segments); the fragment divides them for
  // a true per-column height fraction. Interpolating the ratio itself (the old
  // c.y) facets over the slanted-top quad and streaks — this doesn't, and the
  // fill stays evenly saturated at the curve whatever its height.
  v_top = top;
  v_base = base;
  v_pos = clipY;
  gl_Position = vec4(mix(x0, x1, c.x), clipY, 0.0, 1.0);
}`;
const AREA_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_color;
uniform vec2 u_res;
in float v_top; in float v_base; in float v_pos;
out vec4 outColor;
${GRAD_GLSL}
void main() {
  vec4 premult = vec4(u_color.rgb * u_color.a, u_color.a);
  if (u_gradMode != 0) {
    // 0 at the baseline, 1 exactly at the curve — even at the curve everywhere.
    float denom = v_top - v_base;
    float markT = clamp((v_pos - v_base) / (abs(denom) > 1e-6 ? denom : 1e-6), 0.0, 1.0);
    // Compose the mark opacity (premultiplied) over the gradient sample.
    premult = fcGradSample(fcGradT(markT, u_res)) * u_color.a;
  }
  if (premult.a <= 0.001) discard;
  outColor = premult;
}`;
const RECT_VS = `#version 300 es
in float ax0; in float ax1; in float ay0; in float ay1;
uniform vec2 u_x0map; uniform vec2 u_x1map; uniform vec2 u_y0map; uniform vec2 u_y1map;
uniform vec2 u_x0meta; uniform vec2 u_x1meta; uniform vec2 u_y0meta; uniform vec2 u_y1meta;
uniform int u_xmode; uniform int u_ymode;
uniform vec4 u_edgePad;
uniform vec2 u_res;
in float a_cval; uniform int u_colorMode;
out float v_lutCoord;
out vec2 v_local; out vec2 v_half; out float v_t;
const vec2 corners[4] = vec2[4](vec2(0.,0.), vec2(1.,0.), vec2(0.,1.), vec2(1.,1.));
${AXIS_GLSL}
void main() {
  vec2 c = corners[gl_VertexID];
  float x0 = fcMap(ax0, u_x0map, u_x0meta, u_xmode) + u_edgePad.x;
  float x1 = fcMap(ax1, u_x1map, u_x1meta, u_xmode) + u_edgePad.y;
  float y0 = fcMap(ay0, u_y0map, u_y0meta, u_ymode) + u_edgePad.z;
  float y1 = fcMap(ay1, u_y1map, u_y1meta, u_ymode) + u_edgePad.w;
  v_lutCoord = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
  // Pixel-space local frame for the rounded-corner/stroke SDF (v_half is
  // constant across the quad; v_local interpolates to the fragment offset).
  vec2 pA = (vec2(x0, y0) * 0.5 + 0.5) * u_res;
  vec2 pB = (vec2(x1, y1) * 0.5 + 0.5) * u_res;
  v_half = abs(pB - pA) * 0.5;
  v_local = mix(pA, pB, c) - (pA + pB) * 0.5;
  v_t = c.y;
  gl_Position = vec4(mix(x0, x1, c.x), mix(y0, y1, c.y), 0.0, 1.0);
}`;
const BAR_VS = `#version 300 es
in float a_pos; in float a_v0; in float a_v1; in float a_cval;
uniform vec2 u_pmap; uniform vec2 u_v0map; uniform vec2 u_v1map;
uniform vec2 u_pmeta; uniform vec2 u_v0meta; uniform vec2 u_v1meta;
uniform int u_pmode; uniform int u_vmode;
uniform float u_width; uniform int u_orientation; uniform int u_v0Mode; uniform float u_v0Const;
uniform float u_v0EdgePad;
uniform vec2 u_res;
uniform int u_colorMode;
out float v_lutCoord;
out vec2 v_local; out vec2 v_half; out float v_t;
const vec2 corners[4] = vec2[4](vec2(0.,0.), vec2(1.,0.), vec2(0.,1.), vec2(1.,1.));
${AXIS_GLSL}
void main() {
  vec2 c = corners[gl_VertexID];
  float p = fcMap(a_pos, u_pmap, u_pmeta, u_pmode);
  float halfW = abs(u_width * u_pmap.x) * 0.5;
  float v0 = (u_v0Mode == 0 ? u_v0Const : fcMap(a_v0, u_v0map, u_v0meta, u_vmode)) + u_v0EdgePad;
  float v1 = fcMap(a_v1, u_v1map, u_v1meta, u_vmode);
  v_lutCoord = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
  vec2 clipA, clipB;
  if (u_orientation == 0) {
    clipA = vec2(p - halfW, v0); clipB = vec2(p + halfW, v1);
    gl_Position = vec4(mix(clipA.x, clipB.x, c.x), mix(clipA.y, clipB.y, c.y), 0.0, 1.0);
    v_t = c.y;
  } else {
    clipA = vec2(v0, p - halfW); clipB = vec2(v1, p + halfW);
    gl_Position = vec4(mix(clipA.x, clipB.x, c.x), mix(clipA.y, clipB.y, c.y), 0.0, 1.0);
    v_t = c.x;
  }
  // Pixel-space local frame for the rounded-corner/stroke SDF; v_t runs along
  // the value axis (0 at the base, 1 at the bar tip) for mark-space gradients.
  vec2 pA = (clipA * 0.5 + 0.5) * u_res;
  vec2 pB = (clipB * 0.5 + 0.5) * u_res;
  v_half = abs(pB - pA) * 0.5;
  v_local = vec2(mix(pA.x, pB.x, c.x), mix(pA.y, pB.y, c.y)) - (pA + pB) * 0.5;
}`;
const RECT_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_color; uniform int u_colorMode; uniform sampler2D u_lut;
uniform vec2 u_radius; uniform float u_strokeWidth; uniform vec4 u_stroke;
uniform vec2 u_res;
in float v_lutCoord;
in vec2 v_local; in vec2 v_half; in float v_t;
out vec4 outColor;
${GRAD_GLSL}
void main() {
  vec3 rgb = u_colorMode == 0 ? u_color.rgb : texture(u_lut, vec2(clamp(v_lutCoord, 0.0, 1.0), 0.5)).rgb;
  vec4 premult = vec4(rgb * u_color.a, u_color.a);
  // Compose the mark opacity (u_color.a) over the gradient — premultiplied, so
  // one scalar multiply fades every stop, including a fade-to-transparent.
  if (u_gradMode != 0) premult = fcGradSample(fcGradT(v_t, u_res)) * u_color.a;
  if (u_radius.x > 0.0 || u_radius.y > 0.0 || u_strokeWidth > 0.0) {
    // u_radius = (tip, base) in mark space: v_t > 0.5 is the tip half, so
    // corner_radius=(6, 0) rounds only the value end of the bar. On the
    // straight sides the SDF reduces to |local|-half independent of r, so
    // differing radii meet with no seam.
    float r = min(v_t > 0.5 ? u_radius.x : u_radius.y, min(v_half.x, v_half.y));
    vec2 q = abs(v_local) - (v_half - vec2(r));
    float d = length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - r;
    float aa = 0.75;
    if (u_strokeWidth > 0.0) {
      float inner = 1.0 - smoothstep(-aa, aa, d + u_strokeWidth);
      premult = mix(u_stroke, premult, inner);
    }
    premult *= 1.0 - smoothstep(-aa, aa, d);
  }
  if (premult.a <= 0.001) discard;
  outColor = premult;
}`;
function fcMonotoneTangents(x, y, n) {
const d = new Float64Array(n - 1);
const m = new Float64Array(n);
for (let i = 0; i < n - 1; i++) {
const dx = x[i + 1] - x[i];
d[i] = dx > 0 ? (y[i + 1] - y[i]) / dx : 0;
}
m[0] = d[0];
m[n - 1] = d[n - 2];
for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) * 0.5;
for (let i = 0; i < n - 1; i++) {
if (d[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
const a = m[i] / d[i];
const b = m[i + 1] / d[i];
const s = a * a + b * b;
if (s > 9) {
const t = 3 / Math.sqrt(s);
m[i] = t * a * d[i];
m[i + 1] = t * b * d[i];
}
}
return m;
}
function fcSmoothResample(x, y, extra, n, maxOut) {
if (n < 3) return null;
const sub = Math.max(1, Math.min(16, Math.floor(maxOut / n)));
if (sub <= 1) return null;
for (let i = 0; i < n; i++) {
if (!Number.isFinite(x[i]) || !Number.isFinite(y[i])) return null;
if (i > 0 && x[i] < x[i - 1]) return null;
if (extra && !Number.isFinite(extra[i])) return null;
}
const my = fcMonotoneTangents(x, y, n);
const me = extra ? fcMonotoneTangents(x, extra, n) : null;
const outN = (n - 1) * sub + 1;
const ox = new Float32Array(outN);
const oy = new Float32Array(outN);
const oe = extra ? new Float32Array(outN) : null;
let k = 0;
for (let i = 0; i < n - 1; i++) {
const h = x[i + 1] - x[i];
for (let s = 0; s < sub; s++) {
const t = s / sub;
ox[k] = x[i] + h * t;
if (h > 0) {
const t2 = t * t;
const t3 = t2 * t;
const h00 = 2.0 * t3 - 3.0 * t2 + 1.0;
const h10 = t3 - 2.0 * t2 + t;
const h01 = -2.0 * t3 + 3.0 * t2;
const h11 = t3 - t2;
oy[k] = h00 * y[i] + h10 * h * my[i] + h01 * y[i + 1] + h11 * h * my[i + 1];
if (oe) oe[k] = h00 * extra[i] + h10 * h * me[i] + h01 * extra[i + 1] + h11 * h * me[i + 1];
} else {
oy[k] = y[i];
if (oe) oe[k] = extra[i];
}
k++;
}
}
ox[k] = x[n - 1];
oy[k] = y[n - 1];
if (oe) oe[k] = extra[n - 1];
return { x: ox, y: oy, extra: oe, n: outN };
}
const LOD_DIRECT_POINT_BUDGET = 200000;
const LOD_DRILL_EXIT_FACTOR = 1.15;
function lodFade(view, start, duration = 140) {
if (start === undefined || start === null || duration <= 0 || view._prefersReducedMotion()) {
return 1;
}
const t = Math.min(1, Math.max(0, (view._now() - start) / duration));
return t * t * (3 - 2 * t);
}
function lodDecodeLogU8(buf, maxVal) {
const u8 = buf instanceof ArrayBuffer ? new Uint8Array(buf) : new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
const out = new Float32Array(u8.length);
const denom = Math.log1p(Math.max(0, maxVal || 0));
if (denom > 0) {
for (let i = 0; i < u8.length; i++) {
if (u8[i] > 0) out[i] = Math.expm1((u8[i] / 255) * denom);
}
}
return out;
}
function lodCopyGrid(f32) {
return f32.slice ? f32.slice() : new Float32Array(f32);
}
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
startedAt: view._now(),
duration: target < start ? 420 : 260,
};
}
function lodStepNorm(view, g) {
const anim = g._densityNormAnim;
const d = g.density;
if (!anim || !d || !d.grid || !d.tex) return;
const t = Math.min(1, Math.max(0, (view._now() - anim.startedAt) / anim.duration));
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
return (
cx >= Math.min(win.x0, win.x1) &&
cx <= Math.max(win.x0, win.x1) &&
cy >= Math.min(win.y0, win.y1) &&
cy <= Math.max(win.y0, win.y1)
);
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
if (g._lodPendingAt && view._now() - g._lodPendingAt > 1200) return false;
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
function lodApplyDrill(view, g, upd, buffers) {
const gl = view.gl;
const fresh = !g.drill;
let d = g.drill;
if (!d) {
d = g.drill = { trace: g.trace, xBuf: gl.createBuffer(), yBuf: gl.createBuffer() };
}
d.xAxis = g.xAxis;
d.yAxis = g.yAxis;
gl.bindBuffer(gl.ARRAY_BUFFER, d.xBuf);
gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.x.buf]), gl.STATIC_DRAW);
gl.bindBuffer(gl.ARRAY_BUFFER, d.yBuf);
gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.y.buf]), gl.STATIC_DRAW);
d.xMeta = { offset: upd.x.offset, scale: upd.x.scale };
d.yMeta = { offset: upd.y.offset, scale: upd.y.scale };
d.win = { x0: upd.x_range[0], x1: upd.x_range[1], y0: upd.y_range[0], y1: upd.y_range[1] };
d.n = Math.min(upd.x.len, upd.y.len);
d.visible = upd.visible ?? d.n;
d.seq = upd.drill_seq;
d.selActive = false;
view._hoverId = -1;
view._lastRow = null;
d.colorMode = 0;
d.color = parseColor(view.root, upd.color && upd.color.color, [0.3, 0.47, 0.66, 1]);
if (upd.color && upd.color.buf !== undefined) {
d.colorMode = upd.color.mode === "continuous" ? 1 : 2;
if (!d.cBuf) d.cBuf = gl.createBuffer();
const colorValues = upd.color.dtype === "u8"
? view._asU8(buffers[upd.color.buf])
: view._asF32(buffers[upd.color.buf]);
d.cBuf._fcType = colorValues instanceof Uint8Array ? gl.UNSIGNED_BYTE : gl.FLOAT;
gl.bindBuffer(gl.ARRAY_BUFFER, d.cBuf);
gl.bufferData(gl.ARRAY_BUFFER, colorValues, gl.STATIC_DRAW);
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
if (upd.density_val && upd.density_val.buf !== undefined) {
if (!d.dBuf) d.dBuf = gl.createBuffer();
gl.bindBuffer(gl.ARRAY_BUFFER, d.dBuf);
gl.bufferData(gl.ARRAY_BUFFER, view._asF32(buffers[upd.density_val.buf]), gl.STATIC_DRAW);
d.dlut = view._lut(upd.density_colormap || "viridis");
const first = d.lodBlend === undefined;
d.lodBlend = Math.min(1, upd.lod_blend ?? 0);
if (first) d.lodBlendShown = d.lodBlend;
} else {
d.lodBlend = 0;
}
if (fresh) {
g._drillFadeStart = view._now();
g._drillWasInside = false;
g._drillShownAlpha = 0;
g._drillExitFadeStart = null;
g._drillDying = false;
g._drillDiedInsideWin = false;
return;
}
if (g._drillDying || g._drillExitFadeStart != null) {
lodEnterDrillContinuous(view, g);
}
g._drillDying = false;
g._drillDiedInsideWin = false;
}
function lodDropDrill(view, g) {
const d = g.drill;
if (!d) return;
const gl = view.gl;
view._deleteVaos(d);
for (const b of [d.xBuf, d.yBuf, d.cBuf, d.sBuf, d.selBuf, d.dBuf]) if (b) gl.deleteBuffer(b);
g.drill = null;
g._drillFadeStart = null;
g._drillExitFadeStart = null;
g._drillWasInside = false;
g._drillShownAlpha = null;
g._drillDying = false;
g._drillDiedInsideWin = false;
view._hoverId = -1;
view._lastRow = null;
}
function lodMarkDrillDying(view, g) {
if (!g.drill) return;
g._drillDying = true;
g._drillDiedInsideWin = view._viewInside(g.drill.win);
lodBeginDrillExitContinuous(view, g);
}
function lodDrillExitFade(view, g) {
if (g._drillExitFadeStart === undefined || g._drillExitFadeStart === null) {
g._drillExitFadeStart = view._now();
}
const fade = lodFade(view, g._drillExitFadeStart, LOD_EXIT_FADE_MS);
if (fade >= 1) g._drillExitFadeStart = null;
return fade;
}
const LOD_ENTRY_FADE_MS = 140;
const LOD_EXIT_FADE_MS = 120;
function lodFadeInvert(alpha) {
const a = Math.min(1, Math.max(0, alpha));
return 0.5 - Math.sin(Math.asin(1 - 2 * a) / 3);
}
function lodDrillShownAlpha(view, g) {
if (g._drillExitFadeStart != null) {
return 1 - lodFade(view, g._drillExitFadeStart, LOD_EXIT_FADE_MS);
}
if (g._drillFadeStart != null) {
return lodFade(view, g._drillFadeStart, LOD_ENTRY_FADE_MS);
}
if (g._drillShownAlpha != null) return g._drillShownAlpha;
return g._drillWasInside ? 1 : 0;
}
function lodEnterDrillContinuous(view, g) {
const alpha = lodDrillShownAlpha(view, g);
g._drillShownAlpha = alpha;
g._drillExitFadeStart = null;
g._drillFadeStart =
alpha >= 1 ? null : view._now() - LOD_ENTRY_FADE_MS * lodFadeInvert(alpha);
}
function lodBeginDrillExitContinuous(view, g) {
if (g._drillExitFadeStart != null) return;
const alpha = lodDrillShownAlpha(view, g);
g._drillShownAlpha = alpha;
g._drillFadeStart = null;
g._drillExitFadeStart = view._now() - LOD_EXIT_FADE_MS * lodFadeInvert(1 - alpha);
}
function lodApplyDensityUpdate(view, g, upd, buffers) {
lodMarkDrillDying(view, g);
const d = upd.density;
const grid = d.enc === "log-u8"
? lodDecodeLogU8(buffers[d.buf], d.max)
: lodCopyGrid(view._asF32(buffers[d.buf]));
const normStart = lodNormMax(g, d.max);
const normMax = view._prefersReducedMotion() ? d.max : normStart;
g.densityNormMax = normMax;
g.prevDensity = g.density;
g._densityFadeStart = view._now();
g.density = {
w: d.w, h: d.h, max: d.max, normMax, colormap: d.colormap || g.density.colormap,
xRange: d.x_range, yRange: d.y_range,
grid,
tex: view._uploadGrid(grid, d.w, d.h, normMax),
lut: g.density.lut,
};
if (Object.prototype.hasOwnProperty.call(d, "sample")) {
view._applyDensitySample(g, d.sample, buffers);
}
lodStartNormAnim(view, g, normMax, d.max);
lodRememberDensity(view, g, g.density);
}
function lodDrawDensityWithFade(view, g, density, opacityScale = 1) {
if (density !== g._shownDensity) {
if (density === g._densitySwitchPrev && g._densitySwitchFadeStart != null) {
const f = lodFade(view, g._densitySwitchFadeStart, 140);
g._densitySwitchFadeStart = view._now() - 140 * lodFadeInvert(1 - f);
} else {
g._densitySwitchFadeStart = view._now();
}
g._densitySwitchPrev = g._shownDensity;
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
function lodDrawDensityTier(view, g, x0, x1, y0, y1) {
lodStepNorm(view, g);
const d = g.drill;
if (d && g._drillDying && !g._drillDiedInsideWin && view._viewInside(d.win)) {
g._drillDying = false;
lodEnterDrillContinuous(view, g);
g._drillWasInside = true;
}
const inside = d && !g._drillDying && view._viewInside(d.win);
const density = lodDensityForView(view, g);
if (inside) {
if (!g._drillWasInside || g._drillExitFadeStart != null) lodEnterDrillContinuous(view, g);
g._drillWasInside = true;
g._drillExitFadeStart = null;
const fade = lodFade(view, g._drillFadeStart);
g._drillShownAlpha = fade;
g._shownDensity = fade < 1 ? density : null;
g._densitySwitchPrev = null;
g._densitySwitchFadeStart = null;
if (fade < 1 && density && density.tex) {
view._drawDensity(g, density, 1 - fade);
view._drawPoints(
d,
view._map(d.xMeta, x0, x1, d.xAxis),
view._map(d.yMeta, y0, y1, d.yAxis),
fade
);
view.draw();
} else {
g._drillFadeStart = null;
view._drawPoints(
d,
view._map(d.xMeta, x0, x1, d.xAxis),
view._map(d.yMeta, y0, y1, d.yAxis)
);
}
} else if (density && density.tex) {
if (lodHoldPendingDrill(view, g, d)) {
lodEnterDrillContinuous(view, g);
const fade = lodFade(view, g._drillFadeStart);
g._drillShownAlpha = fade;
if (fade < 1) {
view._drawDensity(g, density, 1 - fade);
view._drawPoints(
d,
view._map(d.xMeta, x0, x1, d.xAxis),
view._map(d.yMeta, y0, y1, d.yAxis),
fade
);
view.draw();
} else {
g._drillFadeStart = null;
view._drawPoints(
d,
view._map(d.xMeta, x0, x1, d.xAxis),
view._map(d.yMeta, y0, y1, d.yAxis)
);
}
if (view._viewAnim) view.draw();
return;
}
const exitingDrill = d && g._drillWasInside;
if (exitingDrill) lodBeginDrillExitContinuous(view, g);
const exitFade = exitingDrill ? lodDrillExitFade(view, g) : 1;
if (d) g._drillShownAlpha = exitingDrill && exitFade < 1 ? 1 - exitFade : 0;
if (exitingDrill && exitFade < 1) {
lodDrawDensityWithFade(view, g, density, exitFade);
view._drawPoints(
d,
view._map(d.xMeta, x0, x1, d.xAxis),
view._map(d.yMeta, y0, y1, d.yAxis),
1 - exitFade
);
view.draw();
} else {
if (g._drillDying) lodDropDrill(view, g);
else if (exitingDrill) g._drillWasInside = false;
lodDrawDensityWithFade(view, g, density);
view._drawDensitySample(g, x0, x1, y0, y1);
}
} else if (d) {
view._drawPoints(
d,
view._map(d.xMeta, x0, x1, d.xAxis),
view._map(d.yMeta, y0, y1, d.yAxis)
);
}
}
const FC_REBIN_WORKER_SRC = `
const DATA = new Map();
self.onmessage = (e) => {
  const m = e.data;
  if (m.type === "init") {
    DATA.set(m.trace, { x: new Float64Array(m.x), y: new Float64Array(m.y) });
    return;
  }
  const d = DATA.get(m.trace);
  if (!d) return;
  const w = m.w, h = m.h;
  const grid = new Float32Array(w * h);
  const sx = w / ((m.x1 - m.x0) || 1);
  const sy = h / ((m.y1 - m.y0) || 1);
  let max = 0;
  const X = d.x, Y = d.y, n = X.length;
  for (let i = 0; i < n; i++) {
    const cx = (X[i] - m.x0) * sx;
    const cy = (Y[i] - m.y0) * sy;
    if (cx < 0 || cy < 0 || cx >= w || cy >= h) continue;
    const v = ++grid[(cy | 0) * w + (cx | 0)];
    if (v > max) max = v;
  }
  self.postMessage(
    { type: "grid", seq: m.seq, trace: m.trace, w, h, max,
      x0: m.x0, x1: m.x1, y0: m.y0, y1: m.y1, grid: grid.buffer },
    [grid.buffer]
  );
};
`;
function fcCreateRebinWorker() {
try {
const url = URL.createObjectURL(
new Blob([FC_REBIN_WORKER_SRC], { type: "application/javascript" })
);
const worker = new Worker(url);
worker._fcUrl = url;
return worker;
} catch (e) {
return null;
}
}
const MARGIN = { l: 62, r: 14, t: 10, b: 42 };
const UNITLESS_STYLE_PROPS = new Set([
"animation-iteration-count",
"aspect-ratio",
"border-image-outset",
"border-image-slice",
"border-image-width",
"column-count",
"flex",
"flex-grow",
"flex-shrink",
"font-weight",
"line-height",
"opacity",
"order",
"orphans",
"tab-size",
"widows",
"z-index",
"zoom",
"fill-opacity",
"flood-opacity",
"stop-opacity",
"stroke-miterlimit",
"stroke-opacity",
]);
const FC_CONTEXT_GOVERNOR = {
views: new Set(),
seq: 1,
budget() {
const v = typeof window !== "undefined" ? window.XY_CONTEXT_BUDGET : null;
return Number.isFinite(v) && v >= 1 ? Math.floor(v) : 12;
},
register(view) {
this.views.add(view);
},
unregister(view) {
view._ctxPendingReservation = false;
this.views.delete(view);
},
reserve(requester) {
const live = [];
let pending = 0;
for (const view of this.views) {
if (view !== requester && view.gl && !view._glLost && !view._destroyed) live.push(view);
if (view !== requester && view._ctxPendingReservation && !view._destroyed) pending += 1;
}
const needsReservation = !requester._ctxPendingReservation;
requester._ctxPendingReservation = true;
let over = live.length + pending + (needsReservation ? 1 : 0) - this.budget();
if (over <= 0) return;
const candidates = live
.filter((view) => !view._ctxVisible)
.sort((a, b) => (a._ctxSeenSeq || 0) - (b._ctxSeenSeq || 0));
for (const view of candidates) {
if (over <= 0) break;
if (view._releaseContext()) over -= 1;
}
},
acquired(requester) {
requester._ctxPendingReservation = false;
},
cancel(requester) {
requester._ctxPendingReservation = false;
},
};
function fcInitiallyVisible(el) {
if (typeof window === "undefined" || !el.getBoundingClientRect) return true;
const rect = el.getBoundingClientRect();
if (!rect.width && !rect.height) return false;
const vh = window.innerHeight || 0;
const vw = window.innerWidth || 0;
return (
rect.bottom > -0.25 * vh && rect.top < 1.25 * vh && rect.right > -0.25 * vw && rect.left < 1.25 * vw
);
}
class ChartView {
constructor(el, spec, buffer, comm) {
if (spec.protocol !== PROTOCOL) {
el.textContent =
`xy: protocol mismatch (client speaks ${PROTOCOL}, kernel sent ${spec.protocol}). ` +
"Update the xy package and restart the kernel.";
throw new Error("protocol mismatch");
}
this.spec = spec;
this.interaction = spec.interaction || {};
this.markStyle = spec.mark_style || {};
this.axes = this._normalizeAxes(spec);
this.comm = comm;
this.seq = 0;
this._densityStamp = 0;
this._viewRequestBurstStart = null;
this._viewAnim = null;
this._animRaf = null;
this._wheelZoomRaf = null;
this._pendingWheelZoom = null;
this._lastLabelDraw = null;
this._lutCache = new Map();
this._listeners = [];
this._glPrograms = [];
this._progCache = new Map();
this._bufSeq = 0;
this._destroyed = false;
this._hoverId = -1;
this._hoverTarget = null;
this._viewEventRaf = null;
this._linkedSource = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
this.dragMode = "pan";
this.fluid = spec.width === "100%";
this.fluidH = spec.height === "100%";
const rect = this.fluid || this.fluidH ? el.getBoundingClientRect() : null;
const cw = this.fluid ? Math.round(rect.width) || 640 : spec.width;
const ch = this.fluidH ? Math.round(rect.height) || 420 : spec.height;
this.size = { w: Math.max(120, cw), h: Math.max(120, ch) };
this._layout();
this._buildDom(el);
this.theme = readTheme(this.root);
this._payload = buffer;
this._glLost = false;
this._ctxReleasedExt = null;
this._ctxReleases = 0;
this._ctxRecoveries = 0;
this._ctxVisible = fcInitiallyVisible(el);
FC_CONTEXT_GOVERNOR.register(this);
if (this._ctxVisible) this._ctxSeenSeq = FC_CONTEXT_GOVERNOR.seq++;
this._contextLossCount = 0;
this._contextRestoreCount = 0;
this._contextRecoveryError = null;
this._initGl(buffer);
this.root.dataset.fcContextState = "ready";
this._initContextLossRecovery();
this._armContextVisibilityWatch();
this._initInteraction();
this._buildModebar(this.root);
if ((this.fluid || this.fluidH) && typeof ResizeObserver !== "undefined") {
this._ro = new ResizeObserver((entries) => {
const r = entries[entries.length - 1].contentRect;
if (r.width || r.height) this._resize(r.width, r.height);
});
this._ro.observe(this.root);
}
this._armVisibilityResizeWatch();
this._armDprWatch();
this.view0 = {
x0: spec.x_axis.range[0], x1: spec.x_axis.range[1],
y0: spec.y_axis.range[0], y1: spec.y_axis.range[1],
};
this.view = { ...this.view0 };
this._initLinkedCharts();
this._themeWatch = window.matchMedia("(prefers-color-scheme: dark)");
this._onScheme = () => this.refreshTheme();
this._themeWatch.addEventListener?.("change", this._onScheme);
this._unsubscribeComm = comm ? comm.onMessage((msg, buffers) => this._onKernelMsg(msg, buffers)) : null;
this.draw();
}
_layout() {
const compact = this.size.w < 520;
const pad = Array.isArray(this.spec.padding) ? this.spec.padding : null;
const marginLeft = pad ? pad[3] : compact ? 46 : MARGIN.l;
const marginRight = pad ? pad[1] : compact ? 8 : MARGIN.r;
const marginTop = pad ? pad[0] : compact ? 6 : MARGIN.t;
const marginBottom = pad ? pad[2] : compact ? 36 : MARGIN.b;
const topAxisRoom = this._axis("x").side === "top" ? (compact ? 26 : 32) : 0;
const top = marginTop + (this.spec.title ? (compact ? 26 : 30) : 0) + topAxisRoom;
const extraRightAxes = Object.values(this.axes || {}).filter((axis) =>
axis && axis.id !== "y" && String(axis.id || "").startsWith("y") && axis.side === "right");
const right = marginRight + (extraRightAxes.length ? (compact ? 42 : 54) : 0);
this.plot = {
x: marginLeft,
y: top,
w: Math.max(40, this.size.w - marginLeft - right),
h: Math.max(40, this.size.h - top - marginBottom),
};
}
_normalizeAxes(spec) {
const axes = { ...(spec.axes || {}) };
if (spec.x_axis) axes.x = spec.x_axis;
if (spec.y_axis) axes.y = spec.y_axis;
for (const [id, axis] of Object.entries(axes)) {
if (axis && typeof axis === "object" && !axis.id) axis.id = id;
}
return axes;
}
_axis(axisId) {
const id = axisId || "x";
return this.axes[id] || (String(id).startsWith("y") ? this.axes.y : this.axes.x) || {};
}
_axisDim(axisId) {
return String(axisId || "x").startsWith("y") ? "y" : "x";
}
_axisMode(axisId) {
return this._axis(axisId).scale === "log" ? 1 : 0;
}
_axisCoord(axis, value) {
const v = Number(value);
if (!Number.isFinite(v)) return NaN;
if (axis && axis.scale === "log") return v > 0 ? Math.log10(v) : NaN;
return v;
}
_axisValue(axis, coord) {
if (axis && axis.scale === "log") return Math.pow(10, coord);
return coord;
}
_axisRange(axisId, view = this.view) {
if (axisId === "x") return [view.x0, view.x1];
if (axisId === "y") return [view.y0, view.y1];
const axis = this._axis(axisId);
const r = axis.range || [0, 1];
return [Number(r[0]), Number(r[1])];
}
_axisTicks(axisId, target) {
const axis = this._axis(axisId);
const [lo, hi] = this._axisRange(axisId);
if (Array.isArray(axis.tick_values)) {
const ticks = axis.tick_values.map(Number).filter((v) => Number.isFinite(v) && v >= lo && v <= hi);
return { ticks, labels: ticks, step: ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) : 1 };
}
if (axis.kind === "time") return timeTicks(lo, hi, target);
if (axis.kind === "category") return categoryTicks(lo, hi, axis.categories || [], target);
if (axis.scale === "log") return logTicks(lo, hi, target);
return linearTicks(lo, hi, target);
}
_axisTickText(axis, value, step) {
if (Array.isArray(axis.tick_values) && Array.isArray(axis.tick_labels)) {
const index = axis.tick_values.findIndex((candidate) => Number(candidate) === Number(value));
if (index >= 0 && index < axis.tick_labels.length) return String(axis.tick_labels[index]);
}
return fmtAxis(axis, value, step);
}
_axisTickTarget(axisId, fallback) {
const axis = this._axis(axisId);
const requested = Number(axis && axis.tick_count);
if (Number.isFinite(requested) && requested > 0) {
return Math.max(1, Math.min(200, requested));
}
return fallback;
}
_dataPx(axisId, value) {
const dim = this._axisDim(axisId);
const axis = this._axis(axisId);
const [lo, hi] = this._axisRange(axisId);
const c0 = this._axisCoord(axis, lo);
const c1 = this._axisCoord(axis, hi);
const c = this._axisCoord(axis, value);
if (![c0, c1, c].every(Number.isFinite) || c1 === c0) return NaN;
if (dim === "x") return this.plot.x + ((c - c0) / (c1 - c0)) * this.plot.w;
return this.plot.y + (1 - (c - c0) / (c1 - c0)) * this.plot.h;
}
_listen(target, type, handler, options) {
target.addEventListener(type, handler, options);
this._listeners.push({ target, type, handler, options });
return handler;
}
_interactionFlag(name, fallback = false) {
const value = this.interaction && this.interaction[name];
return value === undefined ? fallback : value === true;
}
_eventView(source = "view") {
return {
x0: this.view.x0,
x1: this.view.x1,
y0: this.view.y0,
y1: this.view.y1,
source,
};
}
_dispatchChartEvent(name, detail) {
if (!this.root || typeof CustomEvent !== "function") return;
this.root.dispatchEvent(new CustomEvent(`xy:${name}`, {
detail,
bubbles: true,
composed: true,
}));
}
_emitViewChange(source = "view", opts = {}) {
const shouldDispatch = this._interactionFlag("view_change") || this._linkChannel;
if (!shouldDispatch || this._destroyed) return;
const broadcast = opts.broadcast !== false;
this._pendingViewEvent = { source, broadcast };
if (this._viewEventRaf) return;
this._viewEventRaf = requestAnimationFrame(() => {
this._viewEventRaf = null;
const pending = this._pendingViewEvent || { source, broadcast };
this._pendingViewEvent = null;
const detail = this._eventView(pending.source);
if (this._interactionFlag("view_change")) {
this._dispatchChartEvent("view_change", detail);
}
if (this.comm && this._interactionFlag("view_change")) {
this.comm.send({ type: "view_change", ...detail });
}
if (pending.broadcast) this._broadcastLinkedView(detail);
});
}
_initLinkedCharts() {
const group = this.interaction && this.interaction.link_group;
if (!group || typeof BroadcastChannel !== "function") return;
this._linkAxes = Array.isArray(this.interaction.link_axes)
? this.interaction.link_axes.filter((axis) => axis === "x" || axis === "y")
: ["x", "y"];
if (!this._linkAxes.length) this._linkAxes = ["x", "y"];
this._linkChannel = new BroadcastChannel(`xy:${group}`);
this._linkChannel.onmessage = (event) => {
const msg = event.data || {};
if (!msg.view || msg.source === this._linkedSource) return;
const next = { ...this.view };
if (this._linkAxes.includes("x")) {
next.x0 = Number(msg.view.x0);
next.x1 = Number(msg.view.x1);
}
if (this._linkAxes.includes("y")) {
next.y0 = Number(msg.view.y0);
next.y1 = Number(msg.view.y1);
}
if (![next.x0, next.x1, next.y0, next.y1].every(Number.isFinite)) return;
this._setView(next, { animate: false, source: "linked", broadcast: false });
};
}
_broadcastLinkedView(detail) {
if (!this._linkChannel) return;
this._linkChannel.postMessage({ source: this._linkedSource, view: detail });
}
_applyClass(el, className) {
if (typeof className !== "string") return;
for (const token of className.split(/\s+/).filter(Boolean)) {
try { el.classList.add(token); } catch (_) {   }
}
}
_stylePropertyName(key) {
if (key.startsWith("--")) return key;
return key.replace(/[A-Z]/g, (match) => `-${match.toLowerCase()}`);
}
_stylePropertyValue(property, value) {
if (typeof value !== "number") return String(value);
if (!Number.isFinite(value)) return null;
if (property.startsWith("--") || UNITLESS_STYLE_PROPS.has(property)) return String(value);
return `${value}px`;
}
_applyStyle(el, style) {
if (!style || typeof style !== "object" || Array.isArray(style)) return;
for (const [key, value] of Object.entries(style)) {
if (typeof key !== "string") continue;
if (typeof value !== "string" && typeof value !== "number") continue;
const property = this._stylePropertyName(key);
const cssValue = this._stylePropertyValue(property, value);
if (cssValue != null) el.style.setProperty(property, cssValue);
}
}
_applySlot(el, slot) {
if (el && el.dataset) el.dataset.fcSlot = slot;
const dom = this.spec.dom;
if (!dom || typeof dom !== "object") return;
if (slot === "root") this._applyClass(el, dom.class_name);
if (dom.class_names && typeof dom.class_names === "object") {
this._applyClass(el, dom.class_names[slot]);
}
if (slot === "root") this._applyStyle(el, dom.style);
if (dom.styles && typeof dom.styles === "object") {
this._applyStyle(el, dom.styles[slot]);
}
}
_slotStyleValue(slot, property) {
const styles = this.spec.dom?.styles;
const style = styles && typeof styles === "object" ? styles[slot] : null;
if (!style || typeof style !== "object" || Array.isArray(style)) return null;
if (Object.prototype.hasOwnProperty.call(style, property)) return style[property];
return null;
}
_syncContainerSize() {
if (this._destroyed || !(this.fluid || this.fluidH) || !this.root) return;
const rect = this.root.getBoundingClientRect();
if (rect.width || rect.height) this._resize(rect.width, rect.height);
}
_armVisibilityResizeWatch() {
if (!(this.fluid || this.fluidH)) return;
const syncSoon = () => {
if (this._destroyed) return;
requestAnimationFrame(() => this._syncContainerSize());
};
this._listen(window, "resize", syncSoon);
this._listen(window, "pageshow", syncSoon);
this._listen(document, "visibilitychange", syncSoon);
if (typeof IntersectionObserver !== "undefined") {
this._io = new IntersectionObserver((entries) => {
if (entries.some((entry) => entry.isIntersecting || entry.intersectionRatio > 0)) {
syncSoon();
}
});
this._io.observe(this.root);
}
}
_markStateValue(state, property, fallback = null) {
const styles = this.markStyle && typeof this.markStyle === "object" ? this.markStyle[state] : null;
if (!styles || typeof styles !== "object" || Array.isArray(styles)) return fallback;
if (Object.prototype.hasOwnProperty.call(styles, property)) return styles[property];
return fallback;
}
_markStateNumber(state, property, fallback) {
const value = this._markStateValue(state, property, fallback);
if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
return value;
}
_markStatePaint(state, property, fallback) {
const value = this._markStateValue(state, property, fallback);
return typeof value === "string" ? value : fallback;
}
_armDprWatch() {
if (typeof window.matchMedia !== "function") return;
this._dprMq?.removeEventListener?.("change", this._onDprChange);
const mq = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`);
this._onDprChange = () => {
if (this._destroyed) return;
this._resize(this.size.w, this.size.h);
this._armDprWatch();
};
mq.addEventListener?.("change", this._onDprChange, { once: true });
this._dprMq = mq;
}
_initContextLossRecovery() {
this._listen(this.canvas, "webglcontextlost", (e) => {
e.preventDefault();
if (this._destroyed) return;
const governedRelease = this.canvas.dataset.fcCtx === "released";
if (this._glLost && !governedRelease) return;
this._glLost = true;
if (!governedRelease) this.canvas.dataset.fcCtx = "lost";
this._contextLossCount += 1;
this._contextRecoveryError = null;
this.root.dataset.fcContextState = "lost";
this.seq += 1;
if (this._raf) cancelAnimationFrame(this._raf);
this._raf = null;
if (this._wheelZoomRaf) cancelAnimationFrame(this._wheelZoomRaf);
this._wheelZoomRaf = null;
this._pendingWheelZoom = null;
this._cancelViewAnimation();
clearTimeout(this._viewTimer);
this._viewTimer = null;
clearTimeout(this._rebinTimer);
this._rebinTimer = null;
this._viewRequestBurstStart = null;
this._dispatchChartEvent("context_lost", {
loss_count: this._contextLossCount,
});
});
this._listen(this.canvas, "webglcontextrestored", () => {
if (this._destroyed || this._contextRecoveryError) return;
this._lutCache.clear();
this.pickFbo = null;
this.pickTex = null;
try {
this._initGl(this._payload);
} catch (err) {
this._glLost = true;
this._contextRecoveryError = err;
this.root.dataset.fcContextState = "failed";
try { this._destroyGlResources(); } catch (_cleanupErr) {}
this.gl = null;
this._dispatchChartEvent("context_restore_failed", {
loss_count: this._contextLossCount,
message: err instanceof Error ? err.message : String(err),
});
this.root.textContent = "xy: WebGL2 context could not be restored.";
return;
}
this._glLost = false;
this._contextRestoreCount += 1;
this._contextRecoveryError = null;
this.root.dataset.fcContextState = "ready";
this._scheduleViewRequest(this.view, { delay: 0 });
this.draw();
this._dispatchChartEvent("context_restored", {
loss_count: this._contextLossCount,
restore_count: this._contextRestoreCount,
});
});
}
_releaseContext() {
if (this._destroyed || !this.gl || this._glLost || this.gl.isContextLost()) return false;
const ext = this.gl.getExtension("WEBGL_lose_context");
if (!ext) return false;
this._ctxReleasedExt = ext;
this._ctxReleases += 1;
this._glLost = true;
this.canvas.dataset.fcCtx = "released";
if (this._raf) cancelAnimationFrame(this._raf);
this._raf = null;
ext.loseContext();
return true;
}
_recoverContext() {
if (this._destroyed || !this._glLost) return;
this._ctxRecoveries += 1;
if (this._ctxReleasedExt) {
const ext = this._ctxReleasedExt;
this._ctxReleasedExt = null;
try {
FC_CONTEXT_GOVERNOR.reserve(this);
ext.restoreContext();
return;
} catch (_err) {
FC_CONTEXT_GOVERNOR.cancel(this);
}
}
this._rebuildEvictedContext();
}
_rebuildEvictedContext() {
const fresh = this.canvas.cloneNode(false);
for (const record of this._listeners) {
if (record.target === this.canvas) {
this.canvas.removeEventListener(record.type, record.handler, record.options);
fresh.addEventListener(record.type, record.handler, record.options);
record.target = fresh;
}
}
this.canvas.replaceWith(fresh);
this.canvas = fresh;
this._glLost = false;
this._lutCache.clear();
this.pickFbo = null;
this.pickTex = null;
try {
this._initGl(this._payload);
} catch (_err) {
this._glLost = true;
this.canvas.dataset.fcCtx = "lost";
return;
}
this._scheduleViewRequest(this.view, { delay: 0 });
this.draw();
}
_armContextVisibilityWatch() {
if (typeof IntersectionObserver === "undefined") {
this._ctxVisible = true;
return;
}
this._ctxIo = new IntersectionObserver(
(entries) => {
const entry = entries[entries.length - 1];
this._ctxVisible = entry.isIntersecting || entry.intersectionRatio > 0;
if (this._ctxVisible) {
this._ctxSeenSeq = FC_CONTEXT_GOVERNOR.seq++;
if (this._glLost && !this._destroyed) this._recoverContext();
}
},
{ rootMargin: "25% 0px 25% 0px" },
);
this._ctxIo.observe(this.root);
}
_resize(cssW, cssH) {
const w = this.fluid && cssW ? Math.max(120, Math.round(cssW)) : this.size.w;
const h = this.fluidH && cssH ? Math.max(120, Math.round(cssH)) : this.size.h;
const dpr = window.devicePixelRatio || 1;
if (w === this.size.w && h === this.size.h && dpr === this.dpr) return;
this.dpr = dpr;
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
if (
this._legend &&
this._slotStyleValue("legend", "max-height") == null &&
this._slotStyleValue("legend", "maxHeight") == null
) {
this._legend.style.maxHeight = p.h - 12 + "px";
}
this._positionReductionBadges();
this._pickDirty = true;
this.draw();
this._scheduleViewRequest();
}
_buildDom(el) {
const s = this.spec;
const root = document.createElement("div");
root.className = "xy";
root.style.cssText =
`position:relative;width:${this.fluid ? "100%" : this.size.w + "px"};` +
`height:${this.fluidH ? "100%" : this.size.h + "px"};` +
(this.fluidH ? "min-height:120px;" : "") +
"font:12px system-ui,sans-serif;user-select:none;";
this._applySlot(root, "root");
el.appendChild(root);
this.root = root;
ensureChromeStylesheet(root);
if (s.title) {
const t = document.createElement("div");
t.textContent = s.title;
t.style.cssText = "position:absolute;top:6px;left:0;right:0;";
this._applySlot(t, "title");
root.appendChild(t);
}
this.chrome = document.createElement("canvas");
this.chrome.style.cssText = "position:absolute;inset:0;pointer-events:none;";
this._applySlot(this.chrome, "chrome");
root.appendChild(this.chrome);
this.canvas = document.createElement("canvas");
this.canvas.style.cssText =
`position:absolute;left:${this.plot.x}px;top:${this.plot.y}px;` +
`width:${this.plot.w}px;height:${this.plot.h}px;touch-action:none;`;
this._applySlot(this.canvas, "canvas");
root.appendChild(this.canvas);
this.labels = document.createElement("div");
this.labels.style.cssText = "position:absolute;inset:0;pointer-events:none;";
this._applySlot(this.labels, "labels");
root.appendChild(this.labels);
this.tooltip = document.createElement("div");
this.tooltip.style.cssText =
"position:absolute;display:none;pointer-events:none;z-index:5;white-space:nowrap;";
this._applySlot(this.tooltip, "tooltip");
root.appendChild(this.tooltip);
this._buildLegend(root);
this._buildColorbar(root);
this._buildReductionBadges(root);
}
_compactInt(value) {
const n = Number(value);
if (!Number.isFinite(n)) return "0";
return Math.round(n).toLocaleString();
}
_positionReductionBadges() {
if (!this._badges) return;
const rightInset = this.size.w - (this.plot.x + this.plot.w);
const bottomInset = this.size.h - (this.plot.y + this.plot.h);
this._badges.style.right = `${rightInset + 6}px`;
this._badges.style.bottom = `${bottomInset + 6}px`;
}
_reductionBadgeItems() {
const items = [];
const traces = this.gpuTraces && this.gpuTraces.length
? this.gpuTraces
: (this.spec.traces || []);
for (const entry of traces) {
const t = entry.trace || entry;
if (t.tier !== "density" || !t.density) continue;
const sample = entry.sampleOverlay && entry.sampleOverlay.sample
? entry.sampleOverlay.sample
: t.density.sample;
if (sample && Number(sample.n) > 0) {
items.push(`sampled ${this._compactInt(sample.n)} of ${this._compactInt(sample.visible)}`);
}
if (entry._sampleRebinned) items.push("zoom re-binned from sample");
if (t.density.channels_dropped) items.push("aggregated channels");
}
return items;
}
_refreshReductionBadges() {
if (!this._badges) return;
const items = this._reductionBadgeItems();
this._badges.textContent = "";
this._badges.hidden = items.length === 0;
for (const item of items) {
const badge = document.createElement("div");
badge.textContent = item;
this._applySlot(badge, "badge_item");
this._badges.appendChild(badge);
}
this._positionReductionBadges();
}
_buildReductionBadges(root) {
const items = this._reductionBadgeItems();
const hasDensityTrace = (this.spec.traces || []).some((t) => t.tier === "density");
if (!items.length && !hasDensityTrace) return;
const box = document.createElement("div");
box.style.cssText =
"position:absolute;display:flex;flex-direction:column;align-items:flex-end;" +
"pointer-events:none;z-index:4;";
this._applySlot(box, "badge");
root.appendChild(box);
this._badges = box;
this._refreshReductionBadges();
}
_buildLegend(root) {
const s = this.spec;
if (s.show_legend === false) return;
const items = [];
for (const t of s.traces) {
if (t.tier === "density") {
items.push({ swatch: "gradient", cmap: t.density.colormap, name: t.name || "density" });
} else if (t.color && t.color.mode === "categorical") {
t.color.categories.forEach((cat, i) =>
items.push({ swatch: t.color.palette[i], name: cat, symbol: t.kind === "scatter" ? (t.style?.symbol || "circle") : null, style: t.style || {} }));
} else if (t.color && t.color.mode === "continuous") {
items.push({ swatch: "gradient", cmap: t.color.colormap, name: t.name || "value" });
} else if (t.name) {
const c = (t.color && t.color.color) || (t.style && t.style.color);
items.push({ swatch: c, name: t.name, symbol: t.kind === "scatter" ? (t.style?.symbol || "circle") : null, style: t.style || {} });
}
}
if (!items.length) return;
const lg = document.createElement("div");
const options = s.legend || {};
const loc = options.loc || "upper right";
const ncols = Math.max(1, Number(options.ncols) || 1);
const rightInset = this.size.w - (this.plot.x + this.plot.w);
const horizontal = ncols > 1;
const xPos = loc.includes("left")
? `left:${this.plot.x + 6}px;`
: loc.includes("center")
? `left:${this.plot.x + this.plot.w / 2}px;transform:translateX(-50%);`
: `right:${rightInset + 6}px;`;
const yPos = loc.includes("lower")
? `bottom:${this.size.h - (this.plot.y + this.plot.h) + 6}px;`
: loc === "center" || loc.includes("center left") || loc.includes("center right")
? `top:${this.plot.y + this.plot.h / 2}px;transform:${loc.includes("center") && !loc.includes("left") && !loc.includes("right") ? "translate(-50%,-50%)" : "translateY(-50%)"};`
: `top:${this.plot.y + 6}px;`;
lg.style.cssText = `position:absolute;${xPos}${yPos}` +
`display:grid;grid-template-columns:repeat(${horizontal ? ncols : 1},max-content);` +
"overflow:auto;" + `max-height:${this.plot.h - 12}px;`;
this._applySlot(lg, "legend");
if (options.title) {
const title = document.createElement("div");
title.textContent = String(options.title);
title.style.fontWeight = "600";
title.style.gridColumn = `1 / span ${horizontal ? ncols : 1}`;
lg.appendChild(title);
}
for (const it of items) {
const row = document.createElement("div");
this._applySlot(row, "legend_item");
const sw = document.createElement("span");
sw.style.display = "inline-block";
sw.style.verticalAlign = "-1px";
let bg = it.swatch;
if (it.swatch === "gradient") {
const stops = colormapStops(it.cmap);
bg = `linear-gradient(90deg,${stops.map((c) => `rgb(${c[0]},${c[1]},${c[2]})`).join(",")})`;
sw.style.background = bg;
} else if (it.symbol) {
const ns = "http://www.w3.org/2000/svg";
const svg = document.createElementNS(ns, "svg");
svg.setAttribute("viewBox", "0 0 18 14");
svg.setAttribute("width", "18");
svg.setAttribute("height", "14");
const path = document.createElementNS(ns, "path");
const paths = {
square: "M4.5 2.5h9v9h-9z", diamond: "M9 2l5 5-5 5-5-5z",
thin_diamond: "M9 2l3 5-3 5-3-5z",
triangle: "M9 2l-5 10h10z", triangle_down: "M9 12L4 2h10z",
triangle_left: "M4 7L14 2v10z", triangle_right: "M14 7L4 2v10z",
plus_line: "M9 2v10M4 7h10", x_line: "M5 3l8 8M13 3l-8 8",
cross: "M7.5 2h3v3.5H14v3h-3.5V12h-3V8.5H4v-3h3.5z",
x: "M5.5 2L9 5.5 12.5 2 14 3.5 10.5 7 14 10.5 12.5 12 9 8.5 5.5 12 4 10.5 7.5 7 4 3.5z",
pentagon: "M9 2.5L13.28 5.61 11.65 10.64H6.35L4.72 5.61z",
hexagon: "M9 2L13.3 4.5v5L9 12l-4.3-2.5v-5z",
star: "M9 2l1.5 3.1 3.5.5-2.5 2.5.6 3.5L9 10l-3.1 1.6.6-3.5L4 5.6l3.5-.5z"
};
const color = safeCssPaint(this.root, bg);
if (it.symbol === "circle" || it.symbol === "point" || it.symbol === "pixel") {
if (it.symbol === "pixel") path.setAttribute("d", "M8.5 6.5h1v1h-1z");
else path.setAttribute("d", `M9 ${it.symbol === "point" ? 4.75 : 2.5}a${it.symbol === "point" ? 2.25 : 4.5} ${it.symbol === "point" ? 2.25 : 4.5} 0 1 0 0 ${it.symbol === "point" ? 4.5 : 9}a${it.symbol === "point" ? 2.25 : 4.5} ${it.symbol === "point" ? 2.25 : 4.5} 0 1 0 0 -${it.symbol === "point" ? 4.5 : 9}`);
} else path.setAttribute("d", paths[it.symbol] || paths.square);
path.setAttribute("fill", it.symbol.endsWith("_line") ? "none" : color);
path.setAttribute("stroke", color);
path.setAttribute("stroke-width", String(it.style?.stroke_width || 1));
svg.appendChild(path);
sw.appendChild(svg);
sw.style.width = "18px";
sw.style.height = "14px";
} else {
sw.style.background = safeCssPaint(this.root, bg);
}
this._applySlot(sw, "legend_swatch");
row.appendChild(sw);
row.appendChild(document.createTextNode(it.name));
lg.appendChild(row);
}
root.appendChild(lg);
this._legend = lg;
}
_buildColorbar(root) {
const cb = this.spec.colorbar;
if (!cb) return;
const stops = colormapStops(cb.colormap || "viridis");
const box = document.createElement("div");
const horizontal = cb.orientation === "horizontal";
box.style.cssText = horizontal
? `position:absolute;left:${this.plot.x}px;top:${this.plot.y + this.plot.h + 8}px;` +
`width:${this.plot.w}px;height:10px;` +
`background:linear-gradient(to right,${stops.map((c) => `rgb(${c[0]},${c[1]},${c[2]})`).join(",")});`
: `position:absolute;top:${this.plot.y}px;left:${this.plot.x + this.plot.w + 8}px;` +
`width:10px;height:${Math.max(24, this.plot.h)}px;` +
`background:linear-gradient(to top,${stops.map((c) => `rgb(${c[0]},${c[1]},${c[2]})`).join(",")});`;
const domain = cb.domain || [0, 1];
box.title = `${cb.label ? cb.label + ": " : ""}${domain[0]} – ${domain[1]}`;
root.appendChild(box);
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
FC_CONTEXT_GOVERNOR.reserve(this);
const gl = this.canvas.getContext("webgl2", {
antialias: false, premultipliedAlpha: true, alpha: true,
});
if (!gl) {
FC_CONTEXT_GOVERNOR.cancel(this);
this.root.textContent = "xy: WebGL2 unavailable in this browser.";
throw new Error("webgl2 unavailable");
}
this.gl = gl;
FC_CONTEXT_GOVERNOR.acquired(this);
this.canvas.dataset.fcCtx = "live";
gl.enable(gl.BLEND);
gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
this._progCache = new Map();
this._glPrograms = this._progCache;
this.quad = gl.createBuffer();
this.quad._fcId = ++this._bufSeq;
gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
this.quadVao = gl.createVertexArray();
gl.bindVertexArray(this.quadVao);
gl.enableVertexAttribArray(ATTR_SLOTS.a_corner);
gl.vertexAttribPointer(ATTR_SLOTS.a_corner, 2, gl.FLOAT, false, 0, 0);
gl.vertexAttribDivisor(ATTR_SLOTS.a_corner, 0);
gl.bindVertexArray(null);
this.gpuTraces = this.spec.traces.map((t) => this._buildTrace(buffer, t));
this._pickable = this.gpuTraces.some((g) => markOf(g.trace.kind).pointPick && g.tier !== "density");
if (this._pickable) this._initPickTarget();
}
_prog(key, vs, fs) {
let p = this._progCache.get(key);
if (!p) {
p = makeProgram(this.gl, vs, fs);
this._progCache.set(key, p);
}
return p;
}
get pointProg() { return this._prog("point", POINT_VS, POINT_FS); }
get pointSimpleProg() { return this._prog("point-simple", POINT_SIMPLE_VS, POINT_SIMPLE_FS); }
get lineProg() { return this._prog("line", LINE_VS, LINE_FS); }
get segmentProg() { return this._prog("segment", SEGMENT_VS, SEGMENT_FS); }
get meshProg() { return this._prog("mesh", MESH_VS, MESH_FS); }
get areaProg() { return this._prog("area", AREA_VS, AREA_FS); }
get rectProg() { return this._prog("rect", RECT_VS, RECT_FS); }
get barProg() { return this._prog("bar", BAR_VS, RECT_FS); }
get pickProg() { return this._prog("pick", PICK_VS, PICK_FS); }
get densityProg() { return this._prog("density", GRID_VS, DENSITY_FS); }
get heatmapProg() { return this._prog("heatmap", GRID_VS, HEATMAP_FS); }
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
const g = {
trace: t,
tier: t.tier,
color: [0.3, 0.47, 0.66, 1],
xAxis: typeof t.x_axis === "string" ? t.x_axis : "x",
yAxis: typeof t.y_axis === "string" ? t.y_axis : "y",
};
if (t.tier === "density") {
const d = t.density;
const meta = this.spec.columns[d.buf];
const grid = d.enc === "log-u8"
? lodDecodeLogU8(new Uint8Array(buffer, meta.byte_offset, meta.len), d.max)
: new Float32Array(buffer, meta.byte_offset, d.w * d.h);
g.densityNormMax = d.max;
g.density = {
w: d.w, h: d.h, max: d.max, normMax: d.max, colormap: d.colormap,
xRange: d.x_range, yRange: d.y_range,
grid: lodCopyGrid(grid),
tex: this._uploadGrid(grid, d.w, d.h, d.max),
lut: this._lut(d.colormap),
};
g.sampleOverlay = this._buildDensitySample(t, d.sample, buffer);
g._shownDensity = g.density;
lodRememberDensity(this, g, g.density);
return g;
}
markOf(t.kind).build(this, g, t, buffer);
return g;
}
_buildXY(g, t, buffer) {
const x = this._columnView(buffer, this.spec.columns[t.x]);
const y = this._columnView(buffer, this.spec.columns[t.y]);
g.xMeta = { ...this.spec.columns[t.x] };
g.yMeta = { ...this.spec.columns[t.y] };
g.n = Math.min(x.length, y.length);
g._cpu = { x, y, xMeta: g.xMeta, yMeta: g.yMeta };
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
this._pointMarkStyle(g, t);
}
_pointMarkStyle(g, t) {
const s = t.style || {};
g.symbol = { circle: 0, square: 1, diamond: 2, triangle: 3, cross: 4, hexagon: 5, pentagon: 6, star: 7, triangle_down: 8, triangle_left: 9, triangle_right: 10, x: 11, point: 12, pixel: 13, thin_diamond: 14, plus_line: 15, x_line: 16 }[s.symbol] || 0;
g.pointStrokeWidth = Number(s.stroke_width) || 0;
const markOpaque = [g.color[0], g.color[1], g.color[2], 1];
g.pointStroke = s.stroke
? parseColor(this.root, s.stroke, markOpaque)
: g.pointStrokeWidth > 0 ? markOpaque : null;
}
_sampleTraceSpec(parentTrace, sample) {
return {
id: parentTrace.id,
kind: "scatter",
name: parentTrace.name,
style: sample.style || parentTrace.style || {},
tier: "sampled",
x: sample.x && sample.x.col,
y: sample.y && sample.y.col,
x_axis: parentTrace.x_axis,
y_axis: parentTrace.y_axis,
color: sample.color,
size: sample.size,
};
}
_buildDensitySample(parentTrace, sample, buffer) {
if (!sample || !sample.x || !sample.y || sample.x.col === undefined || sample.y.col === undefined) {
return null;
}
const trace = this._sampleTraceSpec(parentTrace, sample);
const g = {
trace,
tier: "sampled",
xAxis: typeof parentTrace.x_axis === "string" ? parentTrace.x_axis : "x",
yAxis: typeof parentTrace.y_axis === "string" ? parentTrace.y_axis : "y",
};
this._buildScatterMark(g, trace, buffer);
g.win = {
x0: sample.x_range[0], x1: sample.x_range[1],
y0: sample.y_range[0], y1: sample.y_range[1],
};
g.sample = { n: sample.n, visible: sample.visible };
return g;
}
_destroyDensitySample(g) {
const s = g && g.sampleOverlay;
if (!s || !this.gl) return;
for (const b of [s.xBuf, s.yBuf, s.cBuf, s.sBuf, s.selBuf, s.dBuf]) {
if (b) this.gl.deleteBuffer(b);
}
g.sampleOverlay = null;
}
_applyDensitySample(g, sample, buffers) {
this._destroyDensitySample(g);
if (!sample || !sample.x || !sample.y || sample.x.buf === undefined || sample.y.buf === undefined) {
this._refreshReductionBadges();
return;
}
const gl = this.gl;
const trace = {
id: g.trace.id,
kind: "scatter",
name: g.trace.name,
style: sample.style || g.trace.style || {},
tier: "sampled",
x_axis: g.trace.x_axis,
y_axis: g.trace.y_axis,
color: sample.color,
size: sample.size,
};
const s = {
trace,
tier: "sampled",
xAxis: g.xAxis,
yAxis: g.yAxis,
xBuf: gl.createBuffer(),
yBuf: gl.createBuffer(),
xMeta: { offset: sample.x.offset, scale: sample.x.scale },
yMeta: { offset: sample.y.offset, scale: sample.y.scale },
n: Math.min(sample.x.len, sample.y.len),
win: {
x0: sample.x_range[0], x1: sample.x_range[1],
y0: sample.y_range[0], y1: sample.y_range[1],
},
sample: { n: sample.n, visible: sample.visible },
selActive: false,
colorMode: 0,
color: parseColor(this.root, sample.color && sample.color.color, [0.3, 0.47, 0.66, 1]),
sizeMode: 0,
size: (sample.size && sample.size.size) || 4.0,
sizeRange: [2, 18],
};
gl.bindBuffer(gl.ARRAY_BUFFER, s.xBuf);
gl.bufferData(gl.ARRAY_BUFFER, this._asF32(buffers[sample.x.buf]), gl.STATIC_DRAW);
gl.bindBuffer(gl.ARRAY_BUFFER, s.yBuf);
gl.bufferData(gl.ARRAY_BUFFER, this._asF32(buffers[sample.y.buf]), gl.STATIC_DRAW);
if (sample.color && sample.color.buf !== undefined) {
s.colorMode = sample.color.mode === "continuous" ? 1 : 2;
s.cBuf = gl.createBuffer();
const colorValues = sample.color.dtype === "u8"
? this._asU8(buffers[sample.color.buf])
: this._asF32(buffers[sample.color.buf]);
s.cBuf._fcType = colorValues instanceof Uint8Array ? gl.UNSIGNED_BYTE : gl.FLOAT;
gl.bindBuffer(gl.ARRAY_BUFFER, s.cBuf);
gl.bufferData(gl.ARRAY_BUFFER, colorValues, gl.STATIC_DRAW);
s.lut = sample.color.mode === "continuous"
? this._lut(sample.color.colormap)
: this._paletteLut(sample.color.palette);
}
if (sample.size && sample.size.mode === "continuous") {
s.sizeMode = 1;
s.sBuf = gl.createBuffer();
gl.bindBuffer(gl.ARRAY_BUFFER, s.sBuf);
gl.bufferData(gl.ARRAY_BUFFER, this._asF32(buffers[sample.size.buf]), gl.STATIC_DRAW);
s.sizeRange = sample.size.range_px;
}
g.sampleOverlay = s;
this._refreshReductionBadges();
}
_drawDensitySample(g, x0, x1, y0, y1, opacityScale = 1) {
const s = g && g.sampleOverlay;
if (!s || !s.n || !this._viewInside(s.win)) return;
this._drawPoints(
s,
this._map(s.xMeta, x0, x1, s.xAxis),
this._map(s.yMeta, y0, y1, s.yAxis),
opacityScale
);
}
_resolveMarkFill(style, markColor) {
const fill = style && style.fill;
if (!fill || !Array.isArray(fill.stops) || fill.stops.length < 2) return null;
const mode = fill.space === "plot" ? 2 : 1;
const dir = { down: 0, up: 1, left: 2, right: 3 }[fill.dir] ?? 0;
const count = Math.min(fill.stops.length, 8);
const pos = new Float32Array(8);
const colors = new Float32Array(32);
for (let i = 0; i < count; i++) {
const stop = fill.stops[i] || [];
pos[i] = Math.min(Math.max(Number(stop[0]) || 0, 0), 1);
const expr = String(stop[1] || "").trim();
const c = expr.toLowerCase() === "currentcolor"
? markColor
: parseColor(this.root, expr, markColor);
colors[i * 4] = c[0] * c[3];
colors[i * 4 + 1] = c[1] * c[3];
colors[i * 4 + 2] = c[2] * c[3];
colors[i * 4 + 3] = c[3];
}
return { mode, dir, count, pos, colors };
}
_setGradientUniforms(prog, grad) {
const gl = this.gl;
const u = (n) => uniformOf(gl, prog, n);
if (!grad) {
gl.uniform1i(u("u_gradMode"), 0);
return;
}
gl.uniform1i(u("u_gradMode"), grad.mode);
gl.uniform1i(u("u_gradDir"), grad.dir);
gl.uniform1i(u("u_gradCount"), grad.count);
gl.uniform1fv(u("u_gradPos"), grad.pos);
gl.uniform4fv(u("u_gradColor"), grad.colors);
}
_setRectStyleUniforms(prog, g) {
const gl = this.gl;
const u = (n) => uniformOf(gl, prog, n);
gl.uniform2f(u("u_res"), this.canvas.width, this.canvas.height);
const cr = g.cornerRadius || [0, 0];
gl.uniform2f(u("u_radius"), cr[0] * this.dpr, cr[1] * this.dpr);
gl.uniform1f(u("u_strokeWidth"), (g.strokeWidth || 0) * this.dpr);
const sc = g.strokeColor || [0, 0, 0, 0];
gl.uniform4f(u("u_stroke"), sc[0] * sc[3], sc[1] * sc[3], sc[2] * sc[3], sc[3]);
this._setGradientUniforms(prog, g.grad);
}
_rectMarkStyleGpu(g, t) {
const s = t.style || {};
const cr = s.corner_radius;
g.cornerRadius = Array.isArray(cr)
? [Number(cr[0]) || 0, Number(cr[1]) || 0]
: [Number(cr) || 0, Number(cr) || 0];
g.strokeWidth = Number(s.stroke_width) || 0;
const opaque = [g.color[0], g.color[1], g.color[2], 1];
g.strokeColor = s.stroke ? parseColor(this.root, s.stroke, opaque) : opaque;
g.grad = this._resolveMarkFill(s, g.color);
}
_smoothArrays(t, x, y, base, n) {
if (!t.style || t.style.curve !== "smooth") return null;
return fcSmoothResample(x, y, base || null, n, 32768);
}
_stepArrays(t, x, y, n) {
const where = t.style && t.style.step;
if (!where || n < 2) return null;
const perGap = where === "mid" ? 3 : 2;
const m = 1 + (n - 1) * perGap;
const sx = new Float32Array(m);
const sy = new Float32Array(m);
sx[0] = x[0];
sy[0] = y[0];
let j = 1;
for (let i = 1; i < n; i++) {
if (where === "pre") {
sx[j] = x[i - 1]; sy[j] = y[i]; j++;
sx[j] = x[i]; sy[j] = y[i]; j++;
} else if (where === "mid") {
const mid = (x[i - 1] + x[i]) * 0.5;
sx[j] = mid; sy[j] = y[i - 1]; j++;
sx[j] = mid; sy[j] = y[i]; j++;
sx[j] = x[i]; sy[j] = y[i]; j++;
} else {
sx[j] = x[i]; sy[j] = y[i - 1]; j++;
sx[j] = x[i]; sy[j] = y[i]; j++;
}
}
return { x: sx, y: sy, n: m };
}
_buildLineMark(g, t, buffer) {
const x = this._columnView(buffer, this.spec.columns[t.x]);
const y = this._columnView(buffer, this.spec.columns[t.y]);
g.xMeta = { ...this.spec.columns[t.x] };
g.yMeta = { ...this.spec.columns[t.y] };
g.n = Math.min(x.length, y.length);
g._cpu = { x, y, xMeta: g.xMeta, yMeta: g.yMeta };
const sm = this._smoothArrays(t, x, y, null, g.n);
const src = sm || { x, y, n: g.n };
const st = this._stepArrays(t, src.x, src.y, src.n);
const drawX = st ? st.x : src.x;
const drawY = st ? st.y : src.y;
g.xBuf = this._upload(drawX);
g.yBuf = this._upload(drawY);
g.n = st ? st.n : src.n;
g._dashX = drawX;
g._dashY = drawY;
g.color = parseColor(this.root, t.style && t.style.color, [0.3, 0.47, 0.66, 1]);
}
_buildSegmentMark(g, t, buffer) {
const x0 = this._columnView(buffer, this.spec.columns[t.x0]);
const x1 = this._columnView(buffer, this.spec.columns[t.x1]);
const y0 = this._columnView(buffer, this.spec.columns[t.y0]);
const y1 = this._columnView(buffer, this.spec.columns[t.y1]);
g.x0Meta = { ...this.spec.columns[t.x0] };
g.x1Meta = { ...this.spec.columns[t.x1] };
g.y0Meta = { ...this.spec.columns[t.y0] };
g.y1Meta = { ...this.spec.columns[t.y1] };
g.n = Math.min(x0.length, x1.length, y0.length, y1.length);
g.x0Buf = this._upload(x0);
g.x1Buf = this._upload(x1);
g.y0Buf = this._upload(y0);
g.y1Buf = this._upload(y1);
g.color = parseColor(this.root, t.style && t.style.color, [0.3, 0.47, 0.66, 1]);
g.colorMode = 0;
if (t.color && t.color.mode === "continuous") {
g.colorMode = 1;
g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
g.lut = this._lut(t.color.colormap);
} else if (t.color && t.color.mode === "categorical") {
g.colorMode = 2;
g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
g.lut = this._paletteLut(t.color.palette);
}
g._cpu = { x: x0, y: y1, xMeta: g.x0Meta, yMeta: g.y1Meta };
}
_buildMeshMark(g, t, buffer) {
for (const name of ["x0", "x1", "x2", "y0", "y1", "y2"]) {
const values = this._columnView(buffer, this.spec.columns[t[name]]);
g[name + "Meta"] = { ...this.spec.columns[t[name]] };
g[name + "Buf"] = this._upload(values);
g.n = g.n === undefined ? values.length : Math.min(g.n, values.length);
}
g.color = parseColor(this.root, t.color && t.color.color, [0.3, 0.47, 0.66, 1]);
g.colorMode = 0;
if (t.color && t.color.mode === "continuous") {
g.colorMode = 1;
g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
g.lut = this._lut(t.color.colormap);
} else if (t.color && t.color.mode === "categorical") {
g.colorMode = 2;
g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
g.lut = this._paletteLut(t.color.palette);
}
const style = t.style || {};
g.meshStrokeWidth = Number(style.stroke_width) || 0;
g.meshStroke = parseColor(this.root, style.stroke || "transparent", [0, 0, 0, 0]);
}
_buildAreaMark(g, t, buffer) {
const x = this._columnView(buffer, this.spec.columns[t.x]);
const y = this._columnView(buffer, this.spec.columns[t.y]);
const base = this._columnView(buffer, this.spec.columns[t.base]);
g.xMeta = { ...this.spec.columns[t.x] };
g.yMeta = { ...this.spec.columns[t.y] };
g.baseMeta = { ...this.spec.columns[t.base] };
g.n = Math.min(x.length, y.length, base.length);
g._cpu = { x, y, base, xMeta: g.xMeta, yMeta: g.yMeta };
const sm = this._smoothArrays(t, x, y, base, g.n);
g.xBuf = this._upload(sm ? sm.x : x);
g.yBuf = this._upload(sm ? sm.y : y);
g.baseBuf = this._upload(sm ? sm.extra : base);
if (sm) g.n = sm.n;
g._dashX = sm ? sm.x : x;
g._dashY = sm ? sm.y : y;
g.color = parseColor(this.root, t.style && t.style.color, [0.3, 0.47, 0.66, 1]);
g.lineColor = parseColor(this.root, t.style && t.style.color, g.color);
g.grad = this._resolveMarkFill(t.style, g.color);
}
_buildRectMark(g, t, buffer) {
const x0 = this._columnView(buffer, this.spec.columns[t.x0]);
const x1 = this._columnView(buffer, this.spec.columns[t.x1]);
const y0 = this._columnView(buffer, this.spec.columns[t.y0]);
const y1 = this._columnView(buffer, this.spec.columns[t.y1]);
g.x0Meta = { ...this.spec.columns[t.x0] };
g.x1Meta = { ...this.spec.columns[t.x1] };
g.y0Meta = { ...this.spec.columns[t.y0] };
g.y1Meta = { ...this.spec.columns[t.y1] };
g.n = Math.min(x0.length, x1.length, y0.length, y1.length);
g._cpuRect = {
x0, x1, y0, y1,
x0Meta: g.x0Meta, x1Meta: g.x1Meta, y0Meta: g.y0Meta, y1Meta: g.y1Meta,
};
g.x0Buf = this._upload(x0);
g.x1Buf = this._upload(x1);
g.y0Buf = this._upload(y0);
g.y1Buf = this._upload(y1);
g.color = parseColor(this.root, t.style && t.style.color, [0.3, 0.47, 0.66, 1]);
g.colorMode = 0;
if (t.color && t.color.mode === "continuous") {
g.colorMode = 1;
g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
g.lut = this._lut(t.color.colormap);
} else if (t.color && t.color.mode === "categorical") {
g.colorMode = 2;
g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
g.lut = this._paletteLut(t.color.palette);
}
this._rectMarkStyleGpu(g, t);
}
_buildBarMark(g, t, buffer) {
const b = t.bar;
if (!b) return this._buildRectMark(g, t, buffer);
const pos = this._columnView(buffer, this.spec.columns[b.pos]);
const v1 = this._columnView(buffer, this.spec.columns[b.value1]);
g.posMeta = { ...this.spec.columns[b.pos] };
g.value1Meta = { ...this.spec.columns[b.value1] };
g.n = Math.min(pos.length, v1.length);
g.posBuf = this._upload(pos);
g.value1Buf = this._upload(v1);
g.orientation = b.orientation === "horizontal" ? 1 : 0;
g.value0Const = b.value0_const ?? 0;
g.value0Mode = b.value0 === undefined ? 0 : 1;
g.width = b.width;
if (g.value0Mode === 1) {
const v0 = this._columnView(buffer, this.spec.columns[b.value0]);
g.value0Meta = { ...this.spec.columns[b.value0] };
g.n = Math.min(g.n, v0.length);
g._cpuValue0 = v0;
g.value0Buf = this._upload(v0);
}
g._cpu = g.orientation === 1
? { x: v1, y: pos, xMeta: g.value1Meta, yMeta: g.posMeta, value0: g._cpuValue0 }
: { x: pos, y: v1, xMeta: g.posMeta, yMeta: g.value1Meta, value0: g._cpuValue0 };
g.color = parseColor(this.root, t.style && t.style.color, [0.3, 0.47, 0.66, 1]);
g.colorMode = 0;
if (t.color && t.color.mode === "continuous") {
g.colorMode = 1;
g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
g.lut = this._lut(t.color.colormap);
} else if (t.color && t.color.mode === "categorical") {
g.colorMode = 2;
g.cBuf = this._upload(this._columnView(buffer, this.spec.columns[t.color.buf]));
g.lut = this._paletteLut(t.color.palette);
}
this._rectMarkStyleGpu(g, t);
}
_buildHeatmapMark(g, t, buffer) {
const h = t.heatmap;
const truecolor = Array.isArray(h.rgba_bufs);
const grid = truecolor
? h.rgba_bufs.map((index) => this._columnView(buffer, this.spec.columns[index]))
: this._columnView(buffer, this.spec.columns[h.buf]);
g.heatmap = {
w: h.w,
h: h.h,
xRange: h.x_range,
yRange: h.y_range,
colormap: h.colormap,
truecolor,
tex: truecolor ? this._uploadRgbaGrid(grid, h.w, h.h) : this._uploadHeatmapGrid(grid, h.w, h.h),
lut: truecolor ? null : this._lut(h.colormap),
};
if (!truecolor) g._cpuHeatmap = { grid };
}
_uploadRgbaGrid(channels, w, h) {
const gl = this.gl;
const tex = gl.createTexture();
const data = new Uint8Array(w * h * 4);
for (let index = 0; index < w * h; index++) {
for (let channel = 0; channel < 4; channel++) {
data[index * 4 + channel] = Math.round(255 * Math.max(0, Math.min(1, channels[channel][index])));
}
}
gl.bindTexture(gl.TEXTURE_2D, tex);
gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
return tex;
}
_uploadGrid(f32, w, h, maxVal) {
const gl = this.gl;
const tex = gl.createTexture();
lodWriteGridTexture(gl, tex, f32, w, h, maxVal);
return tex;
}
_uploadHeatmapGrid(f32, w, h) {
const gl = this.gl;
const tex = gl.createTexture();
const data = new Uint8Array(f32.length);
for (let i = 0; i < f32.length; i++) {
const v = f32[i];
if (Number.isFinite(v)) {
data[i] = Math.max(1, Math.min(255, Math.round(1 + 254 * Math.max(0, Math.min(1, v)))));
}
}
gl.bindTexture(gl.TEXTURE_2D, tex);
const align = gl.getParameter(gl.UNPACK_ALIGNMENT);
gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, w, h, 0, gl.RED, gl.UNSIGNED_BYTE, data);
gl.pixelStorei(gl.UNPACK_ALIGNMENT, align);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
return tex;
}
_columnView(buffer, meta) {
if (meta.dtype === "u8") return new Uint8Array(buffer, meta.byte_offset, meta.len);
return new Float32Array(buffer, meta.byte_offset, meta.len);
}
_upload(view) {
const gl = this.gl;
const buf = gl.createBuffer();
buf._fcId = ++this._bufSeq;
buf._fcType = view instanceof Uint8Array ? gl.UNSIGNED_BYTE : gl.FLOAT;
gl.bindBuffer(gl.ARRAY_BUFFER, buf);
gl.bufferData(gl.ARRAY_BUFFER, view, gl.STATIC_DRAW);
return buf;
}
_bindVao(g, key, parts, setup) {
const gl = this.gl;
if (!g._vaos) g._vaos = new Map();
const sig = parts.join("|");
let entry = g._vaos.get(key);
if (!entry || entry.sig !== sig) {
if (entry) gl.deleteVertexArray(entry.vao);
const vao = gl.createVertexArray();
gl.bindVertexArray(vao);
setup();
entry = { vao, sig };
g._vaos.set(key, entry);
} else {
gl.bindVertexArray(entry.vao);
}
}
_deleteVaos(g) {
if (!g || !g._vaos) return;
const gl = this.gl;
if (gl) for (const { vao } of g._vaos.values()) gl.deleteVertexArray(vao);
g._vaos = null;
}
_vaoAttr(slot, buf, byteOffset, divisor, size = 1) {
const gl = this.gl;
gl.bindBuffer(gl.ARRAY_BUFFER, buf);
gl.enableVertexAttribArray(slot);
gl.vertexAttribPointer(slot, size, buf._fcType || gl.FLOAT, false, 0, byteOffset);
gl.vertexAttribDivisor(slot, divisor);
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
const gl = this.gl;
gl.bindTexture(gl.TEXTURE_2D, this.pickTex);
gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, this.canvas.width, this.canvas.height, 0,
gl.RGBA, gl.UNSIGNED_BYTE, null);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
this._pickW = this.canvas.width;
this._pickH = this.canvas.height;
}
_map(meta, lo, hi, axisId = null) {
if (!axisId) {
const mul = 2 / ((hi - lo) * meta.scale);
const add = ((meta.offset - lo) / (hi - lo)) * 2 - 1;
return [mul, add];
}
const axis = this._axis(axisId);
const c0 = this._axisCoord(axis, lo);
const c1 = this._axisCoord(axis, hi);
if (![c0, c1].every(Number.isFinite) || c1 === c0) return [0, -2];
const mul = 2 / (c1 - c0);
const add = -1 - c0 * mul;
return [mul, add];
}
_mapConst(value, lo, hi, axisId = null) {
if (!axisId) return ((value - lo) / (hi - lo)) * 2 - 1;
const axis = this._axis(axisId);
const c = this._axisCoord(axis, value);
const c0 = this._axisCoord(axis, lo);
const c1 = this._axisCoord(axis, hi);
if (![c, c0, c1].every(Number.isFinite) || c1 === c0) return -2;
return ((c - c0) / (c1 - c0)) * 2 - 1;
}
_edgePadForValue(value, lo, hi, pixels) {
if (!Number.isFinite(value) || !Number.isFinite(lo) || !Number.isFinite(hi) || hi === lo) return 0;
const span = Math.abs(hi - lo);
const eps = span * 1e-10 + 1e-12;
const px = Math.max(1, pixels || 1);
const padPx = Math.max(2, Math.ceil(this.dpr || 1));
if (Math.abs(value - lo) <= eps) return -(2 * padPx) / px;
if (Math.abs(value - hi) <= eps) return (2 * padPx) / px;
return 0;
}
_setAxisUniforms(prog, prefix, meta, axisId) {
const gl = this.gl;
const u = (n) => uniformOf(gl, prog, n);
gl.uniform2f(u(`${prefix}meta`), meta && Number.isFinite(meta.offset) ? meta.offset : 0, meta && meta.scale ? meta.scale : 1);
gl.uniform1i(u(`${prefix}mode`), this._axisMode(axisId));
}
draw() {
if (this._destroyed || this._glLost || !this.gl) return;
if (this._raf) return;
this._raf = requestAnimationFrame(() => {
this._raf = null;
if (this._destroyed) return;
this._drawNow();
});
}
_drawNow() {
if (this._destroyed || !this.gl || this._glLost) return;
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
const [gx0, gx1] = this._axisRange(g.xAxis);
const [gy0, gy1] = this._axisRange(g.yAxis);
lodDrawDensityTier(this, g, gx0, gx1, gy0, gy1);
continue;
}
markOf(g.trace.kind).draw(this, g, x0, x1, y0, y1);
}
this._drawHoverState();
this._pickDirty = true;
this._drawChrome();
}
_now() {
return performance.now();
}
_drawPoints(g, xm, ym, opacityScale = 1) {
const simple =
g.colorMode === 0 && g.sizeMode === 0 && !g.selActive &&
(g.symbol || 0) === 0 && (g.pointStrokeWidth || 0) <= 0 &&
Math.max(g.lodBlendShown ?? 0, g.lodBlend ?? 0) <= 0.001;
if (simple) {
this._drawSimplePoints(g, xm, ym, opacityScale);
return;
}
const gl = this.gl;
const prog = this.pointProg;
gl.useProgram(prog);
const u = (n) => uniformOf(gl, prog, n);
gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
this._setAxisUniforms(prog, "u_x", g.xMeta, g.xAxis);
this._setAxisUniforms(prog, "u_y", g.yMeta, g.yAxis);
gl.uniform1f(u("u_dpr"), this.dpr);
gl.uniform1f(u("u_size"), g.size);
gl.uniform1i(u("u_sizeMode"), g.sizeMode);
gl.uniform2f(u("u_sizeRange"), g.sizeRange[0], g.sizeRange[1]);
gl.uniform1i(u("u_colorMode"), g.colorMode);
gl.uniform1f(u("u_opacity"), (g.trace.style.opacity ?? 0.8) * opacityScale);
gl.uniform1f(u("u_selectedOpacity"), this._markStateNumber("selected", "opacity", 1));
gl.uniform1f(u("u_unselectedOpacity"), this._markStateNumber("unselected", "opacity", 0.12));
const stateColor = (loc, expr) => {
const c = expr ? parseColor(this.root, expr, [0, 0, 0, 1]) : null;
gl.uniform4f(loc, c ? c[0] : 0, c ? c[1] : 0, c ? c[2] : 0, c ? 1 : 0);
};
stateColor(u("u_selColor"), this._markStateValue("selected", "color"));
stateColor(u("u_unselColor"), this._markStateValue("unselected", "color"));
const [r, gg, b] = g.color;
gl.uniform4f(u("u_color"), r, gg, b, 1);
gl.uniform1i(u("u_symbol"), g.symbol || 0);
const sc = g.pointStroke;
gl.uniform1f(u("u_ptStrokeWidth"), sc ? (g.pointStrokeWidth || 0) * this.dpr : 0);
gl.uniform4f(u("u_ptStroke"), sc ? sc[0] * sc[3] : 0, sc ? sc[1] * sc[3] : 0,
sc ? sc[2] * sc[3] : 0, sc ? sc[3] : 0);
gl.uniform1i(u("u_selActive"), g.selActive ? 1 : 0);
const colorOn = g.colorMode !== 0 && g.cBuf;
const sizeOn = g.sizeMode === 1 && g.sBuf;
const selOn = g.selActive && g.selBuf;
if (g.lut) {
gl.activeTexture(gl.TEXTURE0);
gl.bindTexture(gl.TEXTURE_2D, g.lut);
gl.uniform1i(u("u_lut"), 0);
}
const blendTarget = g.lodBlend ?? 0;
let blend = g.lodBlendShown ?? blendTarget;
if (Math.abs(blend - blendTarget) > 0.005 && !this._prefersReducedMotion()) {
const now = this._now();
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
const blendOn = blend > 0.001 && g.dBuf && g.dlut;
if (blendOn) {
gl.activeTexture(gl.TEXTURE1);
gl.bindTexture(gl.TEXTURE_2D, g.dlut);
}
gl.uniform1i(u("u_dlut"), 1);
this._bindVao(
g,
"points",
[
g.xBuf._fcId, g.yBuf._fcId,
colorOn ? g.cBuf._fcId : 0,
sizeOn ? g.sBuf._fcId : 0,
selOn ? g.selBuf._fcId : 0,
blendOn ? g.dBuf._fcId : 0,
],
() => {
this._vaoAttr(ATTR_SLOTS.ax, g.xBuf, 0, 0);
this._vaoAttr(ATTR_SLOTS.ay, g.yBuf, 0, 0);
if (colorOn) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 0);
if (sizeOn) this._vaoAttr(ATTR_SLOTS.a_sval, g.sBuf, 0, 0);
if (selOn) this._vaoAttr(ATTR_SLOTS.a_sel, g.selBuf, 0, 0);
if (blendOn) this._vaoAttr(ATTR_SLOTS.a_dval, g.dBuf, 0, 0);
}
);
if (!colorOn) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
if (!sizeOn) gl.vertexAttrib1f(ATTR_SLOTS.a_sval, 0.5);
if (!selOn) gl.vertexAttrib1f(ATTR_SLOTS.a_sel, 1.0);
if (!blendOn) gl.vertexAttrib1f(ATTR_SLOTS.a_dval, 0);
gl.drawArrays(gl.POINTS, 0, g.n);
}
_drawSimplePoints(g, xm, ym, opacityScale = 1) {
const gl = this.gl;
const prog = this.pointSimpleProg;
gl.useProgram(prog);
const u = (n) => uniformOf(gl, prog, n);
gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
this._setAxisUniforms(prog, "u_x", g.xMeta, g.xAxis);
this._setAxisUniforms(prog, "u_y", g.yMeta, g.yAxis);
gl.uniform1f(u("u_dpr"), this.dpr);
gl.uniform1f(u("u_size"), g.size);
const [r, gg, b] = g.color;
gl.uniform4f(u("u_color"), r, gg, b, (g.trace.style.opacity ?? 0.8) * opacityScale);
this._bindVao(
g,
"points-simple",
[g.xBuf._fcId, g.yBuf._fcId],
() => {
this._vaoAttr(ATTR_SLOTS.ax, g.xBuf, 0, 0);
this._vaoAttr(ATTR_SLOTS.ay, g.yBuf, 0, 0);
}
);
gl.drawArrays(gl.POINTS, 0, g.n);
}
_drawHoverState() {
const hit = this._hoverTarget;
if (!hit || !hit.g) return;
const g = hit.g;
if (g.trace.kind !== "scatter" || g.tier === "density") return;
if (!Number.isInteger(hit.index) || hit.index < 0 || hit.index >= g.n) return;
const [x0, x1] = this._axisRange(g.xAxis);
const [y0, y1] = this._axisRange(g.yAxis);
this._drawHoverPoint(
g,
hit.index,
this._map(g.xMeta, x0, x1, g.xAxis),
this._map(g.yMeta, y0, y1, g.yAxis)
);
}
_drawHoverPoint(g, index, xm, ym) {
const gl = this.gl;
const prog = this.pointProg;
gl.useProgram(prog);
const u = (n) => uniformOf(gl, prog, n);
gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
this._setAxisUniforms(prog, "u_x", g.xMeta, g.xAxis);
this._setAxisUniforms(prog, "u_y", g.yMeta, g.yAxis);
const defaultSize = Math.max((g.size || 4) * 1.75, (g.size || 4) + 5);
const size = Math.max(0, this._markStateNumber("hover", "size", defaultSize));
const opacity = Math.max(0, Math.min(1, this._markStateNumber("hover", "opacity", 0.95)));
const color = parseColor(
this.root,
this._markStatePaint("hover", "color", "rgba(15,23,42,.92)"),
[0.06, 0.09, 0.16, 0.92]
);
gl.uniform1f(u("u_dpr"), this.dpr);
gl.uniform1f(u("u_size"), size);
gl.uniform1i(u("u_sizeMode"), 0);
gl.uniform2f(u("u_sizeRange"), size, size);
gl.uniform1i(u("u_colorMode"), 0);
gl.uniform1f(u("u_opacity"), opacity);
gl.uniform1f(u("u_selectedOpacity"), 1);
gl.uniform1f(u("u_unselectedOpacity"), 1);
gl.uniform4f(u("u_color"), color[0], color[1], color[2], 1);
gl.uniform1i(u("u_selActive"), 0);
gl.uniform1f(u("u_dblend"), 0);
this._bindVao(g, "hover", [g.xBuf._fcId, g.yBuf._fcId], () => {
this._vaoAttr(ATTR_SLOTS.ax, g.xBuf, 0, 0);
this._vaoAttr(ATTR_SLOTS.ay, g.yBuf, 0, 0);
});
gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
gl.vertexAttrib1f(ATTR_SLOTS.a_sval, 0.5);
gl.vertexAttrib1f(ATTR_SLOTS.a_sel, 1);
gl.vertexAttrib1f(ATTR_SLOTS.a_dval, 0);
gl.drawArrays(gl.POINTS, index, 1);
}
_drawDensity(g, density, opacityScale = 1) {
const gl = this.gl;
const prog = this.densityProg;
gl.useProgram(prog);
const u = (n) => uniformOf(gl, prog, n);
const { x0, x1, y0, y1 } = this.view;
const [vx0, vx1] = this._axisRange(g.xAxis);
const [vy0, vy1] = this._axisRange(g.yAxis);
gl.uniform4f(u("u_view"), vx0 ?? x0, vx1 ?? x1, vy0 ?? y0, vy1 ?? y1);
gl.uniform1i(u("u_xmode"), this._axisMode(g.xAxis));
gl.uniform1i(u("u_ymode"), this._axisMode(g.yAxis));
const d = density || g.density;
gl.uniform4f(u("u_gridRange"), d.xRange[0], d.xRange[1], d.yRange[0], d.yRange[1]);
gl.uniform1f(u("u_opacity"), (g.trace.style.opacity ?? 1.0) * opacityScale);
gl.activeTexture(gl.TEXTURE0);
gl.bindTexture(gl.TEXTURE_2D, d.tex);
gl.uniform1i(u("u_grid"), 0);
gl.activeTexture(gl.TEXTURE1);
gl.bindTexture(gl.TEXTURE_2D, d.lut);
gl.uniform1i(u("u_lut"), 1);
gl.bindVertexArray(this.quadVao);
gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
}
_drawHeatmap(g) {
const h = g.heatmap;
if (!h) return;
const gl = this.gl;
const prog = this.heatmapProg;
gl.useProgram(prog);
const u = (n) => uniformOf(gl, prog, n);
const { x0, x1, y0, y1 } = this.view;
const [vx0, vx1] = this._axisRange(g.xAxis);
const [vy0, vy1] = this._axisRange(g.yAxis);
gl.uniform4f(u("u_view"), vx0 ?? x0, vx1 ?? x1, vy0 ?? y0, vy1 ?? y1);
gl.uniform1i(u("u_xmode"), this._axisMode(g.xAxis));
gl.uniform1i(u("u_ymode"), this._axisMode(g.yAxis));
gl.uniform4f(u("u_gridRange"), h.xRange[0], h.xRange[1], h.yRange[0], h.yRange[1]);
gl.uniform1f(u("u_opacity"), g.trace.style.opacity ?? 1.0);
gl.uniform1i(u("u_truecolor"), h.truecolor ? 1 : 0);
gl.activeTexture(gl.TEXTURE0);
gl.bindTexture(gl.TEXTURE_2D, h.tex);
gl.uniform1i(u("u_grid"), 0);
if (!h.truecolor) {
gl.activeTexture(gl.TEXTURE1);
gl.bindTexture(gl.TEXTURE_2D, h.lut);
gl.uniform1i(u("u_lut"), 1);
}
gl.bindVertexArray(this.quadVao);
gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
}
_drawLine(g, xm, ym, color = null, width = null, opacity = null) {
if (g.n < 2) return;
const gl = this.gl;
gl.useProgram(this.lineProg);
const u = (n) => uniformOf(gl, this.lineProg, n);
gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
this._setAxisUniforms(this.lineProg, "u_x", g.xMeta, g.xAxis);
this._setAxisUniforms(this.lineProg, "u_y", g.yMeta, g.yAxis);
gl.uniform2f(u("u_res"), this.canvas.width, this.canvas.height);
gl.uniform1f(u("u_width"), (width ?? g.trace.style.width ?? 1.5) * this.dpr);
const [r, gg, b, a] = color || g.color;
gl.uniform4f(u("u_color"), r, gg, b, a * (opacity ?? g.trace.style.opacity ?? 1));
const dashed = this._lineDash(g);
this._bindVao(
g,
"line",
dashed ? [g.xBuf._fcId, g.yBuf._fcId, g._lenBuf._fcId] : [g.xBuf._fcId, g.yBuf._fcId],
() => {
this._vaoAttr(ATTR_SLOTS.ax0, g.xBuf, 0, 1);
this._vaoAttr(ATTR_SLOTS.ax1, g.xBuf, 4, 1);
this._vaoAttr(ATTR_SLOTS.ay0, g.yBuf, 0, 1);
this._vaoAttr(ATTR_SLOTS.ay1, g.yBuf, 4, 1);
if (dashed) {
this._vaoAttr(ATTR_SLOTS.a_len0, g._lenBuf, 0, 1);
this._vaoAttr(ATTR_SLOTS.a_len1, g._lenBuf, 4, 1);
}
}
);
gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n - 1);
}
_drawSegments(g, xm, ym) {
if (g.n < 1) return;
const gl = this.gl;
const prog = this.segmentProg;
gl.useProgram(prog);
const u = (n) => uniformOf(gl, prog, n);
gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
this._setAxisUniforms(prog, "u_x0", g.x0Meta, g.xAxis);
this._setAxisUniforms(prog, "u_x1", g.x1Meta, g.xAxis);
this._setAxisUniforms(prog, "u_y0", g.y0Meta, g.yAxis);
this._setAxisUniforms(prog, "u_y1", g.y1Meta, g.yAxis);
gl.uniform2f(u("u_res"), this.canvas.width, this.canvas.height);
gl.uniform1f(u("u_width"), (g.trace.style.width ?? 1.5) * this.dpr);
const [r, gg, b, a] = g.color;
gl.uniform4f(u("u_color"), r, gg, b, a * (g.trace.style.opacity ?? 1));
gl.uniform1i(u("u_colorMode"), g.colorMode || 0);
if (g.colorMode && g.lut) {
gl.activeTexture(gl.TEXTURE0);
gl.bindTexture(gl.TEXTURE_2D, g.lut);
gl.uniform1i(u("u_lut"), 0);
}
this._bindVao(
g,
"segment",
[g.x0Buf._fcId, g.x1Buf._fcId, g.y0Buf._fcId, g.y1Buf._fcId, g.colorMode ? g.cBuf._fcId : 0],
() => {
this._vaoAttr(ATTR_SLOTS.ax0, g.x0Buf, 0, 1);
this._vaoAttr(ATTR_SLOTS.ax1, g.x1Buf, 0, 1);
this._vaoAttr(ATTR_SLOTS.ay0, g.y0Buf, 0, 1);
this._vaoAttr(ATTR_SLOTS.ay1, g.y1Buf, 0, 1);
if (g.colorMode) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 1);
}
);
if (!g.colorMode) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n);
}
_drawMesh(g, xm, ym) {
if (g.n < 1) return;
const gl = this.gl;
const prog = this.meshProg;
gl.useProgram(prog);
const u = (n) => uniformOf(gl, prog, n);
gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
for (const name of ["x0", "x1", "x2"]) this._setAxisUniforms(prog, "u_" + name, g[name + "Meta"], g.xAxis);
for (const name of ["y0", "y1", "y2"]) this._setAxisUniforms(prog, "u_" + name, g[name + "Meta"], g.yAxis);
gl.uniform1i(u("u_colorMode"), g.colorMode || 0);
gl.uniform1f(u("u_opacity"), g.trace.style.opacity ?? 1);
gl.uniform4f(u("u_color"), g.color[0], g.color[1], g.color[2], 1);
const stroke = g.meshStroke || [0, 0, 0, 0];
gl.uniform4f(u("u_stroke"), stroke[0] * stroke[3], stroke[1] * stroke[3], stroke[2] * stroke[3], stroke[3]);
gl.uniform1f(u("u_strokeWidth"), g.meshStrokeWidth || 0);
if (g.colorMode && g.lut) {
gl.activeTexture(gl.TEXTURE0);
gl.bindTexture(gl.TEXTURE_2D, g.lut);
gl.uniform1i(u("u_lut"), 0);
}
const parts = ["x0", "x1", "x2", "y0", "y1", "y2"].map((name) => g[name + "Buf"]._fcId);
parts.push(g.colorMode ? g.cBuf._fcId : 0);
this._bindVao(g, "mesh", parts, () => {
for (const name of ["x0", "x1", "x2", "y0", "y1", "y2"]) {
this._vaoAttr(ATTR_SLOTS["a" + name], g[name + "Buf"], 0, 1);
}
if (g.colorMode) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 1);
});
if (!g.colorMode) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
gl.drawArraysInstanced(gl.TRIANGLES, 0, 3, g.n);
}
_lineDash(g) {
const gl = this.gl;
const u = (n) => uniformOf(gl, this.lineProg, n);
const dash = g.trace.style && g.trace.style.dash;
if (!dash || !dash.length || !g._dashX) {
gl.uniform1i(u("u_dashCount"), 0);
return false;
}
const n = g.n;
if (!g._lenArr || g._lenArr.length !== n) g._lenArr = new Float32Array(n);
const lens = g._lenArr;
const dpr = this.dpr;
let px = this._dataPx(g.xAxis, this._decodeValue(g._dashX, g.xMeta, 0));
let py = this._dataPx(g.yAxis, this._decodeValue(g._dashY, g.yMeta, 0));
let acc = 0;
lens[0] = 0;
for (let i = 1; i < n; i++) {
const nx = this._dataPx(g.xAxis, this._decodeValue(g._dashX, g.xMeta, i));
const ny = this._dataPx(g.yAxis, this._decodeValue(g._dashY, g.yMeta, i));
if (Number.isFinite(nx) && Number.isFinite(ny) && Number.isFinite(px) && Number.isFinite(py)) {
acc += Math.hypot(nx - px, ny - py) * dpr;
}
lens[i] = acc;
px = nx;
py = ny;
}
if (!g._lenBuf) g._lenBuf = this._upload(lens);
else {
gl.bindBuffer(gl.ARRAY_BUFFER, g._lenBuf);
gl.bufferData(gl.ARRAY_BUFFER, lens, gl.DYNAMIC_DRAW);
}
const arr = new Float32Array(8);
let period = 0;
const count = Math.min(dash.length, 8);
for (let i = 0; i < count; i++) {
arr[i] = dash[i] * dpr;
period += arr[i];
}
gl.uniform1i(u("u_dashCount"), count);
gl.uniform1fv(u("u_dashArr"), arr);
gl.uniform1f(u("u_dashPeriod"), Math.max(period, 1e-3));
return true;
}
_drawArea(g, xm, ym, bm) {
if (g.n < 2) return;
const gl = this.gl;
const prog = this.areaProg;
gl.useProgram(prog);
const u = (n) => uniformOf(gl, prog, n);
gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
gl.uniform2f(u("u_bmap"), bm[0], bm[1]);
this._setAxisUniforms(prog, "u_x", g.xMeta, g.xAxis);
this._setAxisUniforms(prog, "u_y", g.yMeta, g.yAxis);
this._setAxisUniforms(prog, "u_b", g.baseMeta, g.yAxis);
const [r, gg, b, a] = g.color;
gl.uniform4f(u("u_color"), r, gg, b, a * (g.trace.style.opacity ?? 0.35));
gl.uniform2f(u("u_res"), this.canvas.width, this.canvas.height);
this._setGradientUniforms(prog, g.grad);
this._bindVao(g, "area", [g.xBuf._fcId, g.yBuf._fcId, g.baseBuf._fcId], () => {
this._vaoAttr(ATTR_SLOTS.ax0, g.xBuf, 0, 1);
this._vaoAttr(ATTR_SLOTS.ax1, g.xBuf, 4, 1);
this._vaoAttr(ATTR_SLOTS.ay0, g.yBuf, 0, 1);
this._vaoAttr(ATTR_SLOTS.ay1, g.yBuf, 4, 1);
this._vaoAttr(ATTR_SLOTS.ab0, g.baseBuf, 0, 1);
this._vaoAttr(ATTR_SLOTS.ab1, g.baseBuf, 4, 1);
});
gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n - 1);
}
_drawRects(g, x0, x1, y0, y1, edgePad = [0, 0, 0, 0]) {
if (!g.n) return;
const gl = this.gl;
const prog = this.rectProg;
gl.useProgram(prog);
const u = (n) => uniformOf(gl, prog, n);
gl.uniform2f(u("u_x0map"), x0[0], x0[1]);
gl.uniform2f(u("u_x1map"), x1[0], x1[1]);
gl.uniform2f(u("u_y0map"), y0[0], y0[1]);
gl.uniform2f(u("u_y1map"), y1[0], y1[1]);
this._setAxisUniforms(prog, "u_x0", g.x0Meta, g.xAxis);
this._setAxisUniforms(prog, "u_x1", g.x1Meta, g.xAxis);
this._setAxisUniforms(prog, "u_y0", g.y0Meta, g.yAxis);
this._setAxisUniforms(prog, "u_y1", g.y1Meta, g.yAxis);
gl.uniform1i(u("u_xmode"), this._axisMode(g.xAxis));
gl.uniform1i(u("u_ymode"), this._axisMode(g.yAxis));
gl.uniform4f(u("u_edgePad"), edgePad[0], edgePad[1], edgePad[2], edgePad[3]);
const [r, gg, b, a] = g.color;
gl.uniform4f(u("u_color"), r, gg, b, a * (g.trace.style.opacity ?? 1));
gl.uniform1i(u("u_colorMode"), g.colorMode || 0);
this._setRectStyleUniforms(prog, g);
const colorOn = g.colorMode && g.cBuf;
if (colorOn) {
gl.activeTexture(gl.TEXTURE0);
gl.bindTexture(gl.TEXTURE_2D, g.lut);
gl.uniform1i(u("u_lut"), 0);
}
this._bindVao(
g,
"rects",
[g.x0Buf._fcId, g.x1Buf._fcId, g.y0Buf._fcId, g.y1Buf._fcId, colorOn ? g.cBuf._fcId : 0],
() => {
this._vaoAttr(ATTR_SLOTS.ax0, g.x0Buf, 0, 1);
this._vaoAttr(ATTR_SLOTS.ax1, g.x1Buf, 0, 1);
this._vaoAttr(ATTR_SLOTS.ay0, g.y0Buf, 0, 1);
this._vaoAttr(ATTR_SLOTS.ay1, g.y1Buf, 0, 1);
if (colorOn) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 1);
}
);
if (!colorOn) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n);
}
_drawBars(g, pmap, v1map, v0map, v0Const, v0EdgePad = 0) {
if (!g.n) return;
const gl = this.gl;
const prog = this.barProg;
gl.useProgram(prog);
const u = (n) => uniformOf(gl, prog, n);
gl.uniform2f(u("u_pmap"), pmap[0], pmap[1]);
gl.uniform2f(u("u_v1map"), v1map[0], v1map[1]);
gl.uniform2f(u("u_v0map"), v0map ? v0map[0] : 1, v0map ? v0map[1] : 0);
const pAxis = g.orientation === 1 ? g.yAxis : g.xAxis;
const vAxis = g.orientation === 1 ? g.xAxis : g.yAxis;
this._setAxisUniforms(prog, "u_p", g.posMeta, pAxis);
this._setAxisUniforms(prog, "u_v1", g.value1Meta, vAxis);
this._setAxisUniforms(prog, "u_v0", g.value0Meta, vAxis);
gl.uniform1i(u("u_pmode"), this._axisMode(pAxis));
gl.uniform1i(u("u_vmode"), this._axisMode(vAxis));
gl.uniform1f(u("u_width"), g.width);
gl.uniform1i(u("u_orientation"), g.orientation);
gl.uniform1i(u("u_v0Mode"), g.value0Mode);
gl.uniform1f(u("u_v0Const"), v0Const ?? 0);
gl.uniform1f(u("u_v0EdgePad"), v0EdgePad);
const [r, gg, b, a] = g.color;
gl.uniform4f(u("u_color"), r, gg, b, a * (g.trace.style.opacity ?? 1));
gl.uniform1i(u("u_colorMode"), g.colorMode || 0);
this._setRectStyleUniforms(prog, g);
const v0On = g.value0Mode === 1 && g.value0Buf;
const colorOn = g.colorMode && g.cBuf;
if (colorOn) {
gl.activeTexture(gl.TEXTURE0);
gl.bindTexture(gl.TEXTURE_2D, g.lut);
gl.uniform1i(u("u_lut"), 0);
}
this._bindVao(
g,
"bars",
[
g.posBuf._fcId, g.value1Buf._fcId,
v0On ? g.value0Buf._fcId : 0,
colorOn ? g.cBuf._fcId : 0,
],
() => {
this._vaoAttr(ATTR_SLOTS.a_pos, g.posBuf, 0, 1);
this._vaoAttr(ATTR_SLOTS.a_v1, g.value1Buf, 0, 1);
if (v0On) this._vaoAttr(ATTR_SLOTS.a_v0, g.value0Buf, 0, 1);
if (colorOn) this._vaoAttr(ATTR_SLOTS.a_cval, g.cBuf, 0, 1);
}
);
if (!v0On) gl.vertexAttrib1f(ATTR_SLOTS.a_v0, 0);
if (!colorOn) gl.vertexAttrib1f(ATTR_SLOTS.a_cval, 0);
gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, g.n);
}
_dataPxX(value) {
return this._dataPx("x", value);
}
_dataPxY(value) {
return this._dataPx("y", value);
}
_styleNumber(style, key, fallback) {
if (!style || typeof style !== "object") return fallback;
const value = Number(style[key]);
return Number.isFinite(value) ? value : fallback;
}
_axisStyleNumber(axis, key, fallback) {
return this._styleNumber(axis && axis.style, key, fallback);
}
_axisStylePaint(axis, key, fallback) {
const style = axis && typeof axis.style === "object" ? axis.style : null;
return safeCssPaint(this.root, style && style[key], fallback);
}
_axisStyleValue(axis, key) {
const style = axis && typeof axis.style === "object" ? axis.style : null;
return style && Object.prototype.hasOwnProperty.call(style, key) ? style[key] : undefined;
}
_axisTickLabelStrategy(axis) {
const raw = axis && axis.tick_label_strategy !== undefined
? axis.tick_label_strategy
: this._axisStyleValue(axis, "tick_label_strategy");
const value = String(raw || "auto").replace(/-/g, "_");
return ["auto", "hide", "rotate", "stagger", "none", "off"].includes(value) ? value : "auto";
}
_axisTickLabelAngle(axis) {
const raw = axis && axis.tick_label_angle !== undefined
? axis.tick_label_angle
: this._axisStyleValue(axis, "tick_label_angle");
const angle = Number(raw);
return Number.isFinite(angle) ? angle : null;
}
_axisTickLabelMinGap(axis, dim) {
const raw = axis && axis.tick_label_min_gap !== undefined
? axis.tick_label_min_gap
: this._axisStyleValue(axis, "tick_label_min_gap");
const gap = Number(raw);
return Number.isFinite(gap) && gap >= 0 ? gap : (dim === "x" ? 8 : 4);
}
_estimateTickLabel(text, fontSize) {
const s = String(text || "");
return { w: Math.max(fontSize * 0.7, s.length * fontSize * 0.62), h: fontSize * 1.2 };
}
_tickLabelExtent(label, dim, fontSize) {
const size = this._estimateTickLabel(label.text, fontSize);
const angle = Math.abs(Number(label.angle || 0)) * Math.PI / 180;
return dim === "y"
? Math.abs(Math.sin(angle)) * size.w + Math.abs(Math.cos(angle)) * size.h
: Math.abs(Math.cos(angle)) * size.w + Math.abs(Math.sin(angle)) * size.h;
}
_tickLabelsCollide(labels, dim, fontSize, minGap) {
const rows = new Map();
for (const label of labels) {
const row = Number(label.row || 0);
if (!rows.has(row)) rows.set(row, []);
rows.get(row).push(label);
}
for (const rowLabels of rows.values()) {
rowLabels.sort((a, b) => a.pos - b.pos);
let lastEnd = -Infinity;
for (const label of rowLabels) {
const extent = this._tickLabelExtent(label, dim, fontSize);
const start = label.pos - extent / 2;
const end = label.pos + extent / 2;
if (start < lastEnd + minGap) return true;
lastEnd = end;
}
}
return false;
}
_downsampleTickLabels(labels, dim, fontSize, minGap) {
if (labels.length <= 1) return labels;
for (let stride = 2; stride <= labels.length; stride++) {
const out = labels.filter((_, i) => i % stride === 0);
if (!this._tickLabelsCollide(out, dim, fontSize, minGap)) return out;
}
return labels.slice(0, 1);
}
_layoutTickLabels(axis, dim, labels) {
if (labels.length <= 1) return labels.map((label) => ({ ...label, angle: 0, row: 0 }));
const fontSize = Math.max(8, this._axisStyleNumber(axis, "tick_size", 11));
const minGap = this._axisTickLabelMinGap(axis, dim);
const explicitAngle = this._axisTickLabelAngle(axis);
const baseAngle = explicitAngle === null ? 0 : explicitAngle;
const withBase = labels.map((label) => ({ ...label, angle: baseAngle, row: 0 }));
let strategy = this._axisTickLabelStrategy(axis);
if (strategy === "none") return [];
if (strategy === "off") return [];
if (strategy === "auto") {
if (!this._tickLabelsCollide(withBase, dim, fontSize, minGap)) return withBase;
if (dim === "x" && axis.kind === "category" && labels.length <= 16) strategy = "rotate";
else if (dim === "x" && labels.length <= 24) strategy = "stagger";
else strategy = "hide";
}
let out = withBase;
if (strategy === "rotate" && dim === "x") {
const angle = explicitAngle === null ? (axis.side === "top" ? 35 : -35) : explicitAngle;
out = labels.map((label) => ({ ...label, angle, row: 0 }));
} else if (strategy === "stagger" && dim === "x") {
out = labels.map((label, i) => ({ ...label, angle: baseAngle, row: i % 2 }));
}
if (strategy === "hide" || this._tickLabelsCollide(out, dim, fontSize, minGap)) {
out = this._downsampleTickLabels(out, dim, fontSize, minGap);
}
return out;
}
_axisLabelCss(axis, dim, fallbackCss) {
const rawPosition = axis && axis.label_position;
const hasPosition = rawPosition !== undefined && rawPosition !== null;
const hasOffset = axis && Number.isFinite(Number(axis.label_offset));
const hasAngle = axis && Number.isFinite(Number(axis.label_angle));
if (!hasPosition && !hasOffset && !hasAngle) return { css: fallbackCss, style: null };
if (rawPosition && typeof rawPosition === "object" && !Array.isArray(rawPosition)) {
return { css: "font-weight:500;white-space:nowrap;", style: rawPosition };
}
const p = this.plot;
const position = String(hasPosition ? rawPosition : "center").replace(/-/g, "_");
const inside = position.startsWith("inside_");
const anchor = inside ? position.slice("inside_".length) : position;
const offset = hasOffset ? Number(axis.label_offset) : 0;
const side = axis && axis.side;
const anchorFrac = anchor === "start" ? 0 : (anchor === "end" ? 1 : 0.5);
if (dim === "x") {
const x = p.x + p.w * anchorFrac;
const outsideY = side === "top" ? p.y - 34 : p.y + p.h + 24;
const insideY = side === "top" ? p.y + 12 : p.y + p.h - 12;
const y = (inside ? insideY : outsideY) +
(side === "top" ? (inside ? offset : -offset) : (inside ? -offset : offset));
const translateX = anchor === "start" ? 0 : (anchor === "end" ? -100 : -50);
const angle = hasAngle ? Number(axis.label_angle) : 0;
return {
css:
`left:${x}px;top:${y}px;` +
`transform:translateX(${translateX}%) rotate(${angle}deg);` +
"transform-origin:center;font-weight:500;white-space:nowrap;",
style: null,
};
}
const xOutside = side === "right" ? p.x + p.w + 40 : 10;
const xInside = side === "right" ? p.x + p.w - 12 : p.x + 12;
const x = (inside ? xInside : xOutside) +
(side === "right" ? (inside ? -offset : offset) : (inside ? offset : -offset));
const y = p.y + p.h * (1 - anchorFrac);
const angle = hasAngle ? Number(axis.label_angle) : (side === "right" ? 90 : -90);
return {
css:
`left:${x}px;top:${y}px;` +
`transform:translate(-50%,-50%) rotate(${angle}deg);` +
"transform-origin:center;font-weight:500;white-space:nowrap;",
style: null,
};
}
_drawChrome() {
const s = this.spec;
const dpr = this.dpr;
const ctx = this.chrome.getContext("2d");
ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
ctx.clearRect(0, 0, this.size.w, this.size.h);
const now = this._now();
const labelCadenceMs = this._viewAnim ? 80 : 0;
const updateLabels = labelCadenceMs === 0
|| this._lastLabelDraw === null
|| now - this._lastLabelDraw >= labelCadenceMs;
if (updateLabels) {
this.labels.textContent = "";
this._lastLabelDraw = now;
}
const p = this.plot;
const xAxis = this._axis("x");
const yAxis = this._axis("y");
const hideX = this._axisTickLabelStrategy(xAxis) === "none";
const hideY = this._axisTickLabelStrategy(yAxis) === "none";
const xt = this._axisTicks(
"x",
this._axisTickTarget("x", Math.max(3, p.w / (xAxis.kind === "time" ? 90 : 80))),
);
const yt = this._axisTicks("y", this._axisTickTarget("y", Math.max(3, p.h / 45)));
const xEdge = (px) => Math.min(p.x + p.w - 0.5, Math.max(p.x + 0.5, Math.round(px) + 0.5));
const yEdge = (py) => Math.min(p.y + p.h - 0.5, Math.max(p.y + 0.5, Math.round(py) + 0.5));
ctx.strokeStyle = this._axisStylePaint(xAxis, "grid_color", this.theme.grid);
ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(xAxis, "grid_width", 1));
ctx.beginPath();
for (const v of (hideX ? [] : xt.ticks)) {
const px = this._dataPx("x", v);
if (!Number.isFinite(px)) continue;
const x = xEdge(px);
ctx.moveTo(x, p.y);
ctx.lineTo(x, p.y + p.h);
}
ctx.stroke();
ctx.strokeStyle = this._axisStylePaint(yAxis, "grid_color", this.theme.grid);
ctx.lineWidth = Math.max(0.5, this._axisStyleNumber(yAxis, "grid_width", 1));
ctx.beginPath();
for (const v of (hideY ? [] : yt.ticks)) {
const py = this._dataPx("y", v);
if (!Number.isFinite(py)) continue;
const y = yEdge(py);
ctx.moveTo(p.x, y);
ctx.lineTo(p.x + p.w, y);
}
ctx.stroke();
this._drawAnnotationShapes(ctx);
if (updateLabels) {
const rule = (styleAxis, left, top, w, h) => {
const d = document.createElement("div");
d.style.cssText =
`position:absolute;left:${left}px;top:${top}px;width:${w}px;height:${h}px;` +
`background:${this._axisStylePaint(styleAxis, "axis_color", this.theme.axis)};` +
"pointer-events:none;";
this.labels.appendChild(d);
};
const frameSides = Array.isArray(s.frame_sides)
? s.frame_sides
: [xAxis.side || "bottom", yAxis.side || "left"];
if (!hideY) {
const yWidth = Math.max(1, this._axisStyleNumber(yAxis, "axis_width", 1));
if (frameSides.includes("left")) rule(yAxis, p.x, p.y, yWidth, p.h);
if (frameSides.includes("right")) rule(yAxis, p.x + p.w - yWidth, p.y, yWidth, p.h);
}
if (!hideX) {
const xHeight = Math.max(1, this._axisStyleNumber(xAxis, "axis_width", 1));
if (frameSides.includes("top")) rule(xAxis, p.x, p.y, p.w, xHeight);
if (frameSides.includes("bottom")) rule(xAxis, p.x, p.y + p.h - xHeight, p.w, xHeight);
}
for (const axis of Object.values(this.axes)) {
if (!axis || axis.id === "y" || !String(axis.id || "").startsWith("y")) continue;
const w = Math.max(1, this._axisStyleNumber(axis, "axis_width", 1));
const x = axis.side === "left" ? p.x : p.x + p.w - w;
rule(axis, x, p.y, w, p.h);
}
const tickParts = (axis) => {
const length = Math.max(0, this._axisStyleNumber(axis, "tick_length", 0));
const width = Math.max(0.5, this._axisStyleNumber(axis, "tick_width", 1));
const direction = String(this._axisStyleValue(axis, "tick_direction") || "out");
if (direction === "in") return { inward: length, outward: 0, width };
if (direction === "inout") return { inward: length / 2, outward: length / 2, width };
return { inward: 0, outward: length, width };
};
if (!hideX) {
const tick = tickParts(xAxis);
const side = xAxis.side || "bottom";
const edge = side === "top" ? p.y : p.y + p.h;
for (const value of xt.ticks) {
const x = this._dataPx("x", value);
if (!Number.isFinite(x) || x < p.x - 1 || x > p.x + p.w + 1) continue;
const top = side === "top" ? edge - tick.outward : edge - tick.inward;
rule(xAxis, x - tick.width / 2, top, tick.width, tick.inward + tick.outward);
}
}
if (!hideY) {
const tick = tickParts(yAxis);
const side = yAxis.side || "left";
const edge = side === "right" ? p.x + p.w : p.x;
for (const value of yt.ticks) {
const y = this._dataPx("y", value);
if (!Number.isFinite(y) || y < p.y - 1 || y > p.y + p.h + 1) continue;
const left = side === "right" ? edge - tick.inward : edge - tick.outward;
rule(yAxis, left, y - tick.width / 2, tick.inward + tick.outward, tick.width);
}
}
}
const label = (text, css, axis, kind = "tick", extraStyle = null) => {
if (!updateLabels) return;
const d = document.createElement("div");
d.textContent = text;
d.dataset.fcLabelKind = kind;
d.dataset.fcAxis = axis && axis.id !== undefined ? String(axis.id) : "";
d.dataset.fcAxisSide = axis && axis.side ? String(axis.side) : "";
const colorKey = kind === "label" ? "label_color" : "tick_color";
const sizeKey = kind === "label" ? "label_size" : "tick_size";
let color = "";
if (this._axisStyleValue(axis, colorKey) !== undefined) {
color = `color:${this._axisStylePaint(axis, colorKey, this.theme.label)};`;
}
let size = "";
if (this._axisStyleValue(axis, sizeKey) !== undefined) {
size = `font-size:${Math.max(8, this._axisStyleNumber(axis, sizeKey, 11))}px;`;
}
d.style.cssText = `position:absolute;line-height:1.2;white-space:nowrap;${color}${size}${css}`;
this._applySlot(d, kind === "label" ? "axis_title" : "tick_label");
this._applyStyle(d, extraStyle);
this.labels.appendChild(d);
};
const xLabelCandidates = [];
for (const v of (xt.labels || xt.ticks)) {
const px = this._dataPx("x", v);
if (px < p.x - 1 || px > p.x + p.w + 1) continue;
const text = this._axisTickText(xAxis, v, xt.step);
xLabelCandidates.push({ pos: px, text });
}
for (const item of this._layoutTickLabels(xAxis, "x", xLabelCandidates)) {
const rowOffset = Number(item.row || 0) * (Math.max(8, this._axisStyleNumber(xAxis, "tick_size", 11)) + 4);
const top = xAxis.side === "top" ? p.y - 18 - rowOffset : p.y + p.h + 6 + rowOffset;
const transform = `translateX(-50%) rotate(${Number(item.angle || 0)}deg)`;
const origin = xAxis.side === "top" ? "bottom center" : "top center";
label(
item.text,
`left:${item.pos}px;top:${top}px;transform:${transform};transform-origin:${origin};`,
xAxis,
);
}
const yLabelCandidates = [];
for (const v of (yt.labels || yt.ticks)) {
const py = this._dataPx("y", v);
if (py < p.y - 1 || py > p.y + p.h + 1) continue;
const text = this._axisTickText(yAxis, v, yt.step);
yLabelCandidates.push({ pos: py, text });
}
for (const item of this._layoutTickLabels(yAxis, "y", yLabelCandidates)) {
const angle = Number(item.angle || 0);
const css = yAxis.side === "right"
? `left:${p.x + p.w + 8}px;top:${item.pos}px;transform:translateY(-50%) rotate(${angle}deg);transform-origin:left center;`
: `right:${this.size.w - p.x + 8}px;top:${item.pos}px;transform:translateY(-50%) rotate(${angle}deg);transform-origin:right center;`;
label(item.text, css, yAxis);
}
for (const axis of Object.values(this.axes)) {
if (!axis || axis.id === "y" || !String(axis.id || "").startsWith("y")) continue;
const ticks = this._axisTicks(axis.id, this._axisTickTarget(axis.id, Math.max(3, p.h / 45)));
const labelCandidates = [];
for (const v of (ticks.labels || ticks.ticks)) {
const py = this._dataPx(axis.id, v);
if (py < p.y - 1 || py > p.y + p.h + 1) continue;
const text = this._axisTickText(axis, v, ticks.step);
labelCandidates.push({ pos: py, text });
}
for (const item of this._layoutTickLabels(axis, "y", labelCandidates)) {
const angle = Number(item.angle || 0);
const css = axis.side === "left"
? `right:${this.size.w - p.x + 8}px;top:${item.pos}px;transform:translateY(-50%) rotate(${angle}deg);transform-origin:right center;`
: `left:${p.x + p.w + 8}px;top:${item.pos}px;transform:translateY(-50%) rotate(${angle}deg);transform-origin:left center;`;
label(item.text, css, axis);
}
if (axis.label) {
const fallbackCss = axis.side === "left"
? `left:10px;top:${p.y + p.h / 2}px;transform:rotate(-90deg) translateX(50%);transform-origin:left;font-weight:500;`
: `left:${p.x + p.w + 40}px;top:${p.y + p.h / 2}px;transform:rotate(90deg) translateX(-50%);transform-origin:left;font-weight:500;`;
const placement = this._axisLabelCss(axis, "y", fallbackCss);
label(axis.label, placement.css, axis, "label", placement.style);
}
}
if (s.x_axis.label) {
const top = xAxis.side === "top" ? p.y - 34 : p.y + p.h + 24;
const fallbackCss = `left:${p.x + p.w / 2}px;top:${top}px;transform:translateX(-50%);font-weight:500;`;
const placement = this._axisLabelCss(xAxis, "x", fallbackCss);
label(s.x_axis.label, placement.css, xAxis, "label", placement.style);
}
if (s.y_axis.label) {
const fallbackCss = yAxis.side === "right"
? `left:${p.x + p.w + 40}px;top:${p.y + p.h / 2}px;transform:rotate(90deg) translateX(-50%);transform-origin:left;font-weight:500;`
: `left:10px;top:${p.y + p.h / 2}px;transform:rotate(-90deg) translateX(50%);transform-origin:left;font-weight:500;`;
const placement = this._axisLabelCss(yAxis, "y", fallbackCss);
label(s.y_axis.label, placement.css, yAxis, "label", placement.style);
}
this._drawAnnotationLabels(updateLabels);
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
_renderPick() {
const gl = this.gl;
if (this._pickW !== this.canvas.width || this._pickH !== this.canvas.height) {
this._allocPickTex();
}
gl.bindFramebuffer(gl.FRAMEBUFFER, this.pickFbo);
gl.viewport(0, 0, this.canvas.width, this.canvas.height);
gl.disable(gl.BLEND);
gl.clearColor(0, 0, 0, 0);
gl.clear(gl.COLOR_BUFFER_BIT);
const { x0, x1, y0, y1 } = this.view;
const prog = this.pickProg;
gl.useProgram(prog);
const u = (n) => uniformOf(gl, prog, n);
gl.uniform1f(u("u_dpr"), this.dpr);
let slot = 0;
for (const g of this.gpuTraces) {
const pg = g.tier === "density"
? (g.drill && !g._drillDying && this._viewInside(g.drill.win) ? g.drill : null)
: (markOf(g.trace.kind).pointPick ? g : null);
if (!pg || !pg.n) { g.pickSlot = -1; continue; }
const [px0, px1] = this._axisRange(pg.xAxis || g.xAxis);
const [py0, py1] = this._axisRange(pg.yAxis || g.yAxis);
const xm = this._map(pg.xMeta, px0, px1, pg.xAxis || g.xAxis);
const ym = this._map(pg.yMeta, py0, py1, pg.yAxis || g.yAxis);
gl.uniform2f(u("u_xmap"), xm[0], xm[1]);
gl.uniform2f(u("u_ymap"), ym[0], ym[1]);
this._setAxisUniforms(prog, "u_x", pg.xMeta, pg.xAxis || g.xAxis);
this._setAxisUniforms(prog, "u_y", pg.yMeta, pg.yAxis || g.yAxis);
gl.uniform1f(u("u_size"), pg.size);
gl.uniform1i(u("u_sizeMode"), pg.sizeMode);
gl.uniform2f(u("u_sizeRange"), pg.sizeRange[0], pg.sizeRange[1]);
gl.uniform1i(u("u_slot"), slot);
g.pickSlot = slot;
const sizeOn = pg.sizeMode === 1 && pg.sBuf;
this._bindVao(
pg,
"pick",
[pg.xBuf._fcId, pg.yBuf._fcId, sizeOn ? pg.sBuf._fcId : 0],
() => {
this._vaoAttr(ATTR_SLOTS.ax, pg.xBuf, 0, 0);
this._vaoAttr(ATTR_SLOTS.ay, pg.yBuf, 0, 0);
if (sizeOn) this._vaoAttr(ATTR_SLOTS.a_sval, pg.sBuf, 0, 0);
}
);
if (!sizeOn) gl.vertexAttrib1f(ATTR_SLOTS.a_sval, 0.5);
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
const py = Math.round((this.plot.h - cssY) * this.dpr);
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
_decodeValue(values, meta, index) {
if (!values || !meta || index < 0 || index >= values.length) return NaN;
return values[index] / (meta.scale || 1) + meta.offset;
}
_dataFromCanvas(cssX, cssY, xAxisId = "x", yAxisId = "y") {
const [x0, x1] = this._axisRange(xAxisId);
const [y0, y1] = this._axisRange(yAxisId);
const xAxis = this._axis(xAxisId);
const yAxis = this._axis(yAxisId);
const cx0 = this._axisCoord(xAxis, x0);
const cx1 = this._axisCoord(xAxis, x1);
const cy0 = this._axisCoord(yAxis, y0);
const cy1 = this._axisCoord(yAxis, y1);
if (![cx0, cx1, cy0, cy1].every(Number.isFinite)) return [NaN, NaN];
return [
this._axisValue(xAxis, cx0 + (cssX / this.plot.w) * (cx1 - cx0)),
this._axisValue(yAxis, cy1 - (cssY / this.plot.h) * (cy1 - cy0)),
];
}
_nearestCpuIndex(g, dataX) {
const cpu = g && g._cpu;
if (!cpu || !cpu.x || !cpu.x.length) return -1;
const xMeta = cpu.xMeta || g.xMeta;
const axis = this._axis(g.xAxis);
const target = this._axisCoord(axis, dataX);
let best = -1;
let bestDist = Infinity;
const limit = Math.min(cpu.x.length, g.n || cpu.x.length);
for (let i = 0; i < limit; i++) {
const x = this._decodeValue(cpu.x, xMeta, i);
const d = Math.abs(this._axisCoord(axis, x) - target);
if (d < bestDist) {
bestDist = d;
best = i;
}
}
return best;
}
_hoverAt(cssX, cssY) {
const maxPx = 12;
let best = null;
for (const g of this.gpuTraces) {
if (g.tier === "density") continue;
const [dataX, dataY] = this._dataFromCanvas(cssX, cssY, g.xAxis, g.yAxis);
if (!Number.isFinite(dataX) || !Number.isFinite(dataY)) continue;
if (g.heatmap && g._cpuHeatmap) {
const hit = this._heatmapHover(g, dataX, dataY);
if (hit) return hit;
continue;
}
if (g.trace.bar && g._cpu) {
const hit = this._barHover(g, dataX, dataY);
if (hit) return hit;
continue;
}
if (g._cpuRect) {
const hit = this._rectHover(g, dataX, dataY);
if (hit) return hit;
continue;
}
if (!g._cpu || !g._cpu.x || !g._cpu.y) continue;
const idx = this._nearestCpuIndex(g, dataX);
if (idx < 0) continue;
const x = this._decodeValue(g._cpu.x, g._cpu.xMeta, idx);
const y = this._decodeValue(g._cpu.y, g._cpu.yMeta, idx);
const px = this._dataPx(g.xAxis, x) - this.plot.x;
const py = this._dataPx(g.yAxis, y) - this.plot.y;
const dist = Math.hypot(px - cssX, py - cssY);
if (dist <= maxPx && (!best || dist < best.dist)) {
best = { trace: g.trace.id, index: idx, g, dist, synthetic: true };
}
}
return best;
}
_barHover(g, dataX, dataY) {
const cpu = g._cpu;
const horizontal = g.orientation === 1;
const limit = Math.min(cpu.x.length, cpu.y.length, g.n || cpu.x.length);
for (let i = 0; i < limit; i++) {
const x = this._decodeValue(cpu.x, cpu.xMeta, i);
const y = this._decodeValue(cpu.y, cpu.yMeta, i);
const value0 = g.value0Mode === 1 && cpu.value0
? this._decodeValue(cpu.value0, horizontal ? g.value0Meta : g.value0Meta, i)
: g.value0Const;
const lo = Math.min(value0 ?? 0, horizontal ? x : y);
const hi = Math.max(value0 ?? 0, horizontal ? x : y);
if (horizontal) {
if (dataX >= lo && dataX <= hi && Math.abs(dataY - y) <= g.width / 2) {
return { trace: g.trace.id, index: i, g, synthetic: true };
}
} else if (Math.abs(dataX - x) <= g.width / 2 && dataY >= lo && dataY <= hi) {
return { trace: g.trace.id, index: i, g, synthetic: true };
}
}
return null;
}
_rectHover(g, dataX, dataY) {
const r = g._cpuRect;
const limit = Math.min(r.x0.length, r.x1.length, r.y0.length, r.y1.length, g.n || r.x0.length);
for (let i = 0; i < limit; i++) {
const x0 = this._decodeValue(r.x0, r.x0Meta, i);
const x1 = this._decodeValue(r.x1, r.x1Meta, i);
const y0 = this._decodeValue(r.y0, r.y0Meta, i);
const y1 = this._decodeValue(r.y1, r.y1Meta, i);
if (
dataX >= Math.min(x0, x1) && dataX <= Math.max(x0, x1) &&
dataY >= Math.min(y0, y1) && dataY <= Math.max(y0, y1)
) {
return { trace: g.trace.id, index: i, g, synthetic: true };
}
}
return null;
}
_heatmapHover(g, dataX, dataY) {
const h = g.heatmap;
if (!h || !g._cpuHeatmap) return null;
const [x0, x1] = h.xRange;
const [y0, y1] = h.yRange;
if (dataX < x0 || dataX > x1 || dataY < y0 || dataY > y1) return null;
const col = Math.min(h.w - 1, Math.max(0, Math.floor(((dataX - x0) / (x1 - x0)) * h.w)));
const row = Math.min(h.h - 1, Math.max(0, Math.floor(((dataY - y0) / (y1 - y0)) * h.h)));
return { trace: g.trace.id, index: row * h.w + col, g, heatmap: { row, col }, synthetic: true };
}
_hover(e) {
if (this._transitionActive()) {
const hadHover = this._hoverId !== -1;
this._hoverId = -1;
this._hoverTarget = null;
this.tooltip.style.display = "none";
if (hadHover) this.draw();
return;
}
const rect = this.canvas.getBoundingClientRect();
const cssX = e.clientX - rect.left;
const cssY = e.clientY - rect.top;
const hit = this._pickAt(cssX, cssY) || this._hoverAt(cssX, cssY);
if (!hit) {
const hadHover = this._hoverId !== -1;
this._hoverId = -1;
this._hoverTarget = null;
this.tooltip.style.display = "none";
if (hadHover) this.draw();
return;
}
const id = hit.trace * 1e9 + hit.index;
this._lastHoverXY = { clientX: e.clientX, clientY: e.clientY };
if (id === this._hoverId) {
this._renderTooltip(this._lastRow, e.clientX, e.clientY);
return;
}
this._hoverId = id;
this._hoverTarget = hit;
this._showTooltip(hit, e.clientX, e.clientY);
this.draw();
}
_asF32(b) {
if (b instanceof ArrayBuffer) return new Float32Array(b);
if (b.byteOffset % 4 === 0) {
return new Float32Array(b.buffer, b.byteOffset, Math.floor(b.byteLength / 4));
}
return new Float32Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
}
_asU8(b) {
if (b instanceof ArrayBuffer) return new Uint8Array(b);
return new Uint8Array(b.buffer, b.byteOffset, b.byteLength);
}
_asU32(b) {
if (b instanceof ArrayBuffer) return new Uint32Array(b);
if (b.byteOffset % 4 === 0) {
return new Uint32Array(b.buffer, b.byteOffset, Math.floor(b.byteLength / 4));
}
return new Uint32Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
}
refreshTheme() {
if (this._destroyed) return;
this.theme = readTheme(this.root);
for (const g of this.gpuTraces) {
markOf(g.trace.kind).refreshColor?.(this, g);
}
this.draw();
}
destroy() {
if (this._destroyed) return;
this._destroyed = true;
FC_CONTEXT_GOVERNOR.unregister(this);
this._ctxIo?.disconnect();
this._ctxIo = null;
clearTimeout(this._rebinTimer);
if (this._rebinWorker) {
this._rebinWorker.terminate();
if (this._rebinWorker._fcUrl) URL.revokeObjectURL(this._rebinWorker._fcUrl);
this._rebinWorker = null;
}
this._ro?.disconnect();
this._io?.disconnect();
this._io = null;
this._themeWatch?.removeEventListener?.("change", this._onScheme);
this._dprMq?.removeEventListener?.("change", this._onDprChange);
this._dprMq = null;
this._unsubscribeComm?.();
this._unsubscribeComm = null;
for (const { target, type, handler, options } of this._listeners.splice(0)) {
target.removeEventListener(type, handler, options);
}
clearTimeout(this._viewTimer);
this._viewTimer = null;
if (this._viewEventRaf) cancelAnimationFrame(this._viewEventRaf);
this._viewEventRaf = null;
if (this._wheelZoomRaf) cancelAnimationFrame(this._wheelZoomRaf);
this._wheelZoomRaf = null;
this._pendingWheelZoom = null;
this._linkChannel?.close?.();
this._linkChannel = null;
if (this._raf) cancelAnimationFrame(this._raf);
this._raf = null;
this._cancelViewAnimation();
this._destroyGlResources();
this.gl = null;
this.root.remove();
}
_deleteBuffers(obj, names) {
const gl = this.gl;
if (!gl || !obj) return;
const seen = new Set();
for (const name of names) {
const buf = obj[name];
if (buf && !seen.has(buf)) {
seen.add(buf);
gl.deleteBuffer(buf);
}
obj[name] = null;
}
}
_destroyTraceResources(g, texSeen) {
if (!g) return;
this._destroyDensitySample(g);
this._deleteVaos(g);
this._deleteVaos(g.drill);
this._deleteBuffers(g, [
"xBuf", "yBuf", "cBuf", "sBuf", "selBuf", "baseBuf",
"x0Buf", "x1Buf", "x2Buf", "y0Buf", "y1Buf", "y2Buf",
"posBuf", "value1Buf", "value0Buf",
]);
this._deleteBuffers(g.drill, ["xBuf", "yBuf", "cBuf", "sBuf", "selBuf", "dBuf"]);
const textures = [];
if (g.heatmap) textures.push(g.heatmap.tex);
for (const d of g.densityCache || []) textures.push(d && d.tex);
if (g.density) textures.push(g.density.tex);
if (g._shownDensity) textures.push(g._shownDensity.tex);
for (const tex of textures) {
if (tex && !texSeen.has(tex)) {
texSeen.add(tex);
this.gl.deleteTexture(tex);
}
}
g.drill = null;
g.density = null;
g._shownDensity = null;
g.densityCache = [];
g.heatmap = null;
g._cpu = null;
}
_destroyGlResources() {
const gl = this.gl;
if (!gl) return;
const texSeen = new Set();
for (const g of this.gpuTraces || []) this._destroyTraceResources(g, texSeen);
for (const tex of this._lutCache.values()) {
if (tex && !texSeen.has(tex)) {
texSeen.add(tex);
gl.deleteTexture(tex);
}
}
this._lutCache.clear();
if (this.pickFbo) gl.deleteFramebuffer(this.pickFbo);
if (this.pickTex && !texSeen.has(this.pickTex)) gl.deleteTexture(this.pickTex);
this.pickFbo = null;
this.pickTex = null;
if (this.quad) gl.deleteBuffer(this.quad);
this.quad = null;
if (this.quadVao) gl.deleteVertexArray(this.quadVao);
this.quadVao = null;
for (const p of this._progCache ? this._progCache.values() : []) {
if (p) gl.deleteProgram(p);
}
if (this._progCache) this._progCache.clear();
this._glPrograms = this._progCache;
this.gpuTraces = [];
}
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
d.style.cssText =
`position:absolute;left:${px + dx}px;top:${py + dy}px;` +
`transform:translate(${anchor},0);pointer-events:none;` +
`white-space:pre-line;text-align:center;`;
this._applySlot(d, "annotation_label");
this._applyClass(d, ann.class_name);
this._applyStyle(d, style);
if (style && (style.label_color || style.color)) {
d.style.color = this._annotationLabelPaint(style, this.theme.label);
}
this.labels.appendChild(d);
}
},
});
Object.assign(ChartView.prototype, {
_showTooltip(hit, clientX, clientY) {
const row = this._localRow(hit);
this._lastRow = row;
this._renderTooltip(row, clientX, clientY);
if (this._interactionFlag("hover")) {
this._dispatchChartEvent("hover", {
row,
trace: hit.trace,
index: hit.index,
view: this._eventView("hover"),
});
}
if (this.comm) {
this._pickSeq = (this._pickSeq || 0) + 1;
const req = { type: "pick", seq: this._pickSeq, trace: hit.trace, index: hit.index };
const hg = hit.g;
if (hg && hg.tier === "density" && hg.drill && hg.drill.seq !== undefined) {
req.drill_seq = hg.drill.seq;
}
this.comm.send(req);
}
},
_localRow(hit) {
const g = hit.g;
const cpu = g._cpu;
const row = { trace: g.trace.id, index: hit.index };
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
} else if (g._cpuRect) {
const r = g._cpuRect;
const x0 = this._decodeValue(r.x0, r.x0Meta, hit.index);
const x1 = this._decodeValue(r.x1, r.x1Meta, hit.index);
const y0 = this._decodeValue(r.y0, r.y0Meta, hit.index);
const y1 = this._decodeValue(r.y1, r.y1Meta, hit.index);
row.x = x0 + (x1 - x0) / 2;
row.y = y1;
row.x_kind = r.x0Meta.kind;
row.y_kind = r.y1Meta.kind;
} else if (cpu) {
const xMeta = cpu.xMeta || g.xMeta;
const yMeta = cpu.yMeta || g.yMeta;
row.x = this._decodeValue(cpu.x, xMeta, hit.index);
row.y = this._decodeValue(cpu.y, yMeta, hit.index);
row.x_kind = xMeta && xMeta.kind;
row.y_kind = yMeta && yMeta.kind;
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
_renderTooltip(row, clientX, clientY) {
if (!row || this.spec.show_tooltip === false) {
this.tooltip.style.display = "none";
return;
}
const rect = this.root.getBoundingClientRect();
const lx = clientX - rect.left;
const ly = clientY - rect.top;
const lines = this._tooltipLines(row);
this.tooltip.textContent = "";
lines.forEach((ln, i) => {
if (i) this.tooltip.appendChild(document.createElement("br"));
this.tooltip.appendChild(document.createTextNode(ln));
});
this.tooltip.style.display = "block";
const tw = this.tooltip.offsetWidth;
this.tooltip.style.left = Math.min(lx + 12, this.size.w - tw - 4) + "px";
this.tooltip.style.top = ly + 12 + "px";
},
});
Object.assign(ChartView.prototype, {
_initInteraction() {
const c = this.canvas;
let drag = null;
let band = null;
this.selRect = document.createElement("div");
this.selRect.style.cssText = "position:absolute;display:none;pointer-events:none;z-index:4;";
this._applySlot(this.selRect, "selection");
this.root.appendChild(this.selRect);
if (this._interactionFlag("crosshair")) {
this.crosshairX = document.createElement("div");
this.crosshairX.style.cssText =
"position:absolute;display:none;pointer-events:none;z-index:3;width:1px;";
this._applySlot(this.crosshairX, "crosshair_x");
this.root.appendChild(this.crosshairX);
this.crosshairY = document.createElement("div");
this.crosshairY.style.cssText =
"position:absolute;display:none;pointer-events:none;z-index:3;height:1px;";
this._applySlot(this.crosshairY, "crosshair_y");
this.root.appendChild(this.crosshairY);
}
const dataAt = (clientX, clientY) => {
const r = c.getBoundingClientRect();
return this._dataFromCanvas(clientX - r.left, clientY - r.top);
};
this._listen(c, "pointerdown", (e) => {
this._cancelViewAnimation();
const canBrush = this._interactionFlag("brush", true) && this._interactionFlag("select", true);
const mode = e.shiftKey && canBrush && this._pickable ? "select"
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
});
this._listen(c, "pointermove", (e) => {
if (band) { this._updateBand(band, e); return; }
if (drag) {
drag.moved = true;
const { x0, x1, y0, y1 } = drag.view;
const xa = this._axis("x");
const ya = this._axis("y");
const cx0 = this._axisCoord(xa, x0), cx1 = this._axisCoord(xa, x1);
const cy0 = this._axisCoord(ya, y0), cy1 = this._axisCoord(ya, y1);
const dx = ((e.clientX - drag.px) / this.plot.w) * (cx1 - cx0);
const dy = ((e.clientY - drag.py) / this.plot.h) * (cy1 - cy0);
this.view = {
x0: this._axisValue(xa, cx0 - dx),
x1: this._axisValue(xa, cx1 - dx),
y0: this._axisValue(ya, cy0 + dy),
y1: this._axisValue(ya, cy1 + dy),
};
this.draw();
this._scheduleViewRequest();
this._emitViewChange("pan");
return;
}
this._updateCrosshair(e);
this._hover(e);
});
const end = (e) => {
if (band) {
this.selRect.style.display = "none";
const d1 = dataAt(e.clientX, e.clientY);
const moved = Math.abs(e.clientX - band.sx) > 3 || Math.abs(e.clientY - band.sy) > 3;
if (moved) {
if (band.mode === "zoom") this._zoomToBox(band.d0, d1, true);
else this._sendSelect(band.d0, d1);
this._ignoreNextClick = true;
}
band = null;
return;
}
if (drag && drag.moved) this._ignoreNextClick = true;
if (drag && !drag.moved) this.tooltip.style.display = "none";
drag = null;
};
this._listen(c, "pointerup", end);
this._listen(c, "pointercancel", () => { this.selRect.style.display = "none"; band = null; drag = null; });
this._listen(c, "pointerleave", () => {
const hadHover = this._hoverId !== -1;
this._hoverId = -1;
this._hoverTarget = null;
this.tooltip.style.display = "none";
this._hideCrosshair();
if (this._interactionFlag("hover")) {
this._dispatchChartEvent("leave", { view: this._eventView("leave") });
}
if (hadHover) this.draw();
});
this._listen(c, "click", (e) => this._click(e));
this._listen(c, "wheel", (e) => {
e.preventDefault();
const f = Math.pow(1.0015, e.deltaY);
const r = c.getBoundingClientRect();
const fx = (e.clientX - r.left) / r.width;
const fy = 1 - (e.clientY - r.top) / r.height;
this._queueWheelZoom(f, fx, fy);
}, { passive: false });
this._listen(c, "dblclick", () => {
this._clearSelection();
this._setView(this.view0, { animate: true });
});
},
_updateCrosshair(e) {
if (!this.crosshairX || !this.crosshairY) return;
const rect = this.canvas.getBoundingClientRect();
const rootRect = this.root.getBoundingClientRect();
const x = e.clientX - rect.left;
const y = e.clientY - rect.top;
if (x < 0 || x > rect.width || y < 0 || y > rect.height) {
this._hideCrosshair();
return;
}
const left = e.clientX - rootRect.left;
const top = e.clientY - rootRect.top;
this.crosshairX.style.display = "block";
this.crosshairX.style.left = left + "px";
this.crosshairX.style.top = this.plot.y + "px";
this.crosshairX.style.height = this.plot.h + "px";
this.crosshairY.style.display = "block";
this.crosshairY.style.left = this.plot.x + "px";
this.crosshairY.style.top = top + "px";
this.crosshairY.style.width = this.plot.w + "px";
},
_hideCrosshair() {
if (this.crosshairX) this.crosshairX.style.display = "none";
if (this.crosshairY) this.crosshairY.style.display = "none";
},
_click(e) {
if (this._ignoreNextClick) {
this._ignoreNextClick = false;
return;
}
if (!this._interactionFlag("click")) return;
const rect = this.canvas.getBoundingClientRect();
const cssX = e.clientX - rect.left;
const cssY = e.clientY - rect.top;
const [x, y] = this._dataFromCanvas(cssX, cssY);
const hit = this._pickAt(cssX, cssY) || this._hoverAt(cssX, cssY);
const detail = {
x,
y,
view: this._eventView("click"),
row: hit && this._localRow ? this._localRow(hit) : null,
trace: hit ? hit.trace : null,
index: hit ? hit.index : null,
};
this._dispatchChartEvent("click", detail);
if (hit && this.comm) {
const msg = { type: "click", trace: hit.trace, index: hit.index };
const g = hit.g;
if (g && g.tier === "density" && g.drill && g.drill.seq !== undefined) {
msg.drill_seq = g.drill.seq;
}
this.comm.send(msg);
}
},
_updateBand(band, e) {
const rect = this.canvas.getBoundingClientRect();
const rootRect = this.root.getBoundingClientRect();
const x = Math.min(band.sx, e.clientX) - rootRect.left;
const y = Math.min(band.sy, e.clientY) - rootRect.top;
const w = Math.abs(e.clientX - band.sx);
const h = Math.abs(e.clientY - band.sy);
const px = this.plot.x, py = this.plot.y;
const x2 = Math.min(x + w, px + this.plot.w), y2 = Math.min(y + h, py + this.plot.h);
const cx = Math.max(x, px), cy = Math.max(y, py);
if (band.mode === "zoom") {
this.selRect.style.border = "1px solid var(--chart-zoom-selection, rgba(120,120,120,.9))";
this.selRect.style.background = "var(--chart-zoom-selection-fill, rgba(120,120,120,.12))";
} else {
this.selRect.style.border = "1px solid var(--chart-selection, rgba(90,140,240,.9))";
this.selRect.style.background = "var(--chart-selection-fill, rgba(90,140,240,.15))";
}
this.selRect.style.display = "block";
this.selRect.style.left = cx + "px";
this.selRect.style.top = cy + "px";
this.selRect.style.width = Math.max(0, x2 - cx) + "px";
this.selRect.style.height = Math.max(0, y2 - cy) + "px";
void rect;
},
_sendSelect(d0, d1) {
const x0 = Math.min(d0[0], d1[0]), x1 = Math.max(d0[0], d1[0]);
const y0 = Math.min(d0[1], d1[1]), y1 = Math.max(d0[1], d1[1]);
const range = { x0, x1, y0, y1 };
this._dispatchChartEvent("brush", { range, view: this._eventView("brush") });
if (this.comm) {
this.comm.send({ type: "select", x0, x1, y0, y1 });
} else {
this._selectLocal(x0, x1, y0, y1);
}
},
_selectLocal(x0, x1, y0, y1) {
let total = 0;
for (const g of this.gpuTraces) {
if (!g._cpu || g.tier === "density") continue;
const cx = g._cpu.x, cy = g._cpu.y;
const xMeta = g._cpu.xMeta || g.xMeta;
const yMeta = g._cpu.yMeta || g.yMeta;
const ox = xMeta.offset, sx = xMeta.scale || 1;
const oy = yMeta.offset, sy = yMeta.scale || 1;
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
this._dispatchChartEvent("select", {
total,
range: { x0, x1, y0, y1 },
view: this._eventView("select"),
});
},
_applySelMask(g, maskF32) {
const gl = this.gl;
if (!g.selBuf) g.selBuf = gl.createBuffer();
gl.bindBuffer(gl.ARRAY_BUFFER, g.selBuf);
gl.bufferData(gl.ARRAY_BUFFER, maskF32, gl.STATIC_DRAW);
g.selActive = true;
},
_clearSelection() {
for (const g of this.gpuTraces) {
g.selActive = false;
if (g.drill) g.drill.selActive = false;
}
this._selectionCount = 0;
if (this._interactionFlag("select", true)) {
if (this.comm) this.comm.send({ type: "select_clear" });
this._dispatchChartEvent("select", { total: 0, view: this._eventView("select_clear") });
}
},
_buildModebar(root) {
if (this.spec.show_modebar === false) return;
const bar = document.createElement("div");
bar.style.cssText =
`position:absolute;top:${this.plot.y + 4}px;left:${this.plot.x + 4}px;z-index:6;` +
"display:flex;opacity:.72;transition:opacity .15s;";
this._applySlot(bar, "modebar");
this._listen(root, "pointerenter", () => { bar.style.opacity = "1"; });
this._listen(root, "pointerleave", () => { bar.style.opacity = ".72"; });
this._modebar = bar;
this._modeBtns = {};
const mk = (name, title, onClick, toggles) => {
const b = document.createElement("button");
b.type = "button";
b.title = title;
b.innerHTML = this._icon(name);
b.style.cssText =
"display:flex;align-items:center;justify-content:center;pointer-events:auto;";
this._applySlot(b, "modebar_button");
this._listen(b, "pointerdown", (e) => e.stopPropagation());
this._listen(b, "click", (e) => { e.stopPropagation(); onClick(); });
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
},
_setDragMode(mode) {
this.dragMode = mode;
if (this.canvas) this.canvas.dataset.fcDragmode = mode;
for (const [name, btn] of Object.entries(this._modeBtns || {})) {
btn.classList.toggle("fc-active", name === mode);
}
},
_prefersReducedMotion() {
return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true;
},
_cancelViewAnimation() {
if (this._animRaf) cancelAnimationFrame(this._animRaf);
this._animRaf = null;
this._viewAnim = null;
},
_setView(next, opts = {}) {
if (this._destroyed) return;
const target = { x0: next.x0, x1: next.x1, y0: next.y0, y1: next.y1 };
const animate = opts.animate === true && !this._prefersReducedMotion();
const duration = opts.duration || 180;
if (!animate || duration <= 0) {
this._cancelViewAnimation();
this.view = target;
this.draw();
if (opts.request !== false) this._scheduleViewRequest();
this._emitViewChange(opts.source || "view", { broadcast: opts.broadcast });
return;
}
clearTimeout(this._viewTimer);
this.seq += 1;
const request = opts.request !== false;
const requestDelay = opts.requestDelay ?? Math.min(55, Math.max(24, duration * 0.35));
const requestMaxWait = opts.requestMaxWait ?? 130;
if (request) {
this._scheduleViewRequest(target, { seq: this.seq, delay: requestDelay, maxWait: requestMaxWait });
}
const now = this._now();
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
if (this._destroyed) { this._animRaf = null; return; }
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
this._emitViewChange(opts.source || "view", { broadcast: opts.broadcast });
}
};
this._animRaf = requestAnimationFrame(step);
},
_zoomBy(f, animate = false) {
const base = this._viewAnim ? this._viewAnim.target : this.view;
const { x0, x1, y0, y1 } = base;
const xr = this._zoomAxisRange("x", x0, x1, f, 0.5);
const yr = this._zoomAxisRange("y", y0, y1, f, 0.5);
if (!xr || !yr) return;
this._setView({ x0: xr[0], x1: xr[1], y0: yr[0], y1: yr[1] }, { animate });
},
_zoomAxisRange(axisId, lo, hi, f, anchorFrac) {
const axis = this._axis(axisId);
const c0 = this._axisCoord(axis, lo);
const c1 = this._axisCoord(axis, hi);
if (![c0, c1].every(Number.isFinite) || c0 === c1) return null;
const ca = c0 + anchorFrac * (c1 - c0);
if (f < 1) {
const minSpan = Math.max(Math.abs(ca), 1e-30) * 1e-12;
if (Math.abs((c1 - c0) * f) < minSpan) return null;
}
return [
this._axisValue(axis, ca - (ca - c0) * f),
this._axisValue(axis, ca + (c1 - ca) * f),
];
},
_zoomAt(f, fx, fy, animate = false, duration = 120) {
const base = this._viewAnim ? this._viewAnim.target : this.view;
const { x0, x1, y0, y1 } = base;
const xr = this._zoomAxisRange("x", x0, x1, f, fx);
const yr = this._zoomAxisRange("y", y0, y1, f, fy);
if (!xr || !yr) return;
this._setView({ x0: xr[0], x1: xr[1], y0: yr[0], y1: yr[1] }, { animate, duration });
},
_queueWheelZoom(factor, fx, fy) {
if (!Number.isFinite(factor) || factor <= 0) return;
if (!this._pendingWheelZoom) {
this._pendingWheelZoom = { factor: 1, fx, fy };
}
this._pendingWheelZoom.factor *= factor;
this._pendingWheelZoom.fx = fx;
this._pendingWheelZoom.fy = fy;
if (this._wheelZoomRaf) return;
this._wheelZoomRaf = requestAnimationFrame(() => {
this._wheelZoomRaf = null;
const pending = this._pendingWheelZoom;
this._pendingWheelZoom = null;
if (!pending || this._destroyed) return;
this._zoomAt(pending.factor, pending.fx, pending.fy, false);
});
},
_zoomToBox(d0, d1, animate = false) {
const xa = this._axis("x");
const ya = this._axis("y");
const xlo = Math.min(d0[0], d1[0]), xhi = Math.max(d0[0], d1[0]);
const ylo = Math.min(d0[1], d1[1]), yhi = Math.max(d0[1], d1[1]);
const cx0 = this._axisCoord(xa, xlo), cx1 = this._axisCoord(xa, xhi);
const cy0 = this._axisCoord(ya, ylo), cy1 = this._axisCoord(ya, yhi);
if (![cx0, cx1, cy0, cy1].every(Number.isFinite)) return;
const minSpanX = Math.max(Math.abs(cx0), Math.abs(cx1), 1e-30) * 1e-12;
const minSpanY = Math.max(Math.abs(cy0), Math.abs(cy1), 1e-30) * 1e-12;
if (Math.abs(cx1 - cx0) < minSpanX || Math.abs(cy1 - cy0) < minSpanY) return;
const xReversed = this.view.x1 < this.view.x0;
const yReversed = this.view.y1 < this.view.y0;
const x0 = xReversed ? xhi : xlo;
const x1 = xReversed ? xlo : xhi;
const y0 = yReversed ? yhi : ylo;
const y1 = yReversed ? ylo : yhi;
this._setView({ x0, x1, y0, y1 }, { animate });
},
_icon(name) {
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
},
});
Object.assign(ChartView.prototype, {
_scheduleViewRequest(viewOverride = this.view, opts = {}) {
if (this._destroyed || this._glLost) return;
if (!this.comm) {
this._scheduleSampleRebin(viewOverride, opts);
return;
}
const needsDecimated = this.spec.traces.some((t) => t.tier === "decimated");
const needsDensity = this.gpuTraces.some((g) => g.tier === "density");
if (!needsDecimated && !needsDensity) return;
const seq = opts.seq ?? ++this.seq;
const view = { ...viewOverride };
const plotW = Math.round(this.plot.w);
const plotH = Math.round(this.plot.h);
if (needsDensity) {
const now = this._now();
for (const g of this.gpuTraces) {
if (g.tier !== "density") continue;
g._lodPendingView = view;
g._lodPendingSeq = seq;
g._lodPendingAt = now;
}
}
let delay = opts.delay ?? 120;
if (opts.maxWait !== undefined && opts.maxWait !== null) {
const now = this._now();
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
if (this._destroyed) return;
this._viewRequestBurstStart = null;
if (seq !== this.seq) return;
if (needsDecimated) {
this.comm.send({
type: "view", seq,
x0: Math.min(view.x0, view.x1), x1: Math.max(view.x0, view.x1), px: plotW,
});
}
if (needsDensity) {
for (const g of this.gpuTraces) {
if (g.tier !== "density") continue;
this.comm.send({
type: "density_view", seq, trace: g.trace.id,
x0: Math.min(view.x0, view.x1), x1: Math.max(view.x0, view.x1),
y0: Math.min(view.y0, view.y1), y1: Math.max(view.y0, view.y1),
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
},
_scheduleSampleRebin(viewOverride = this.view, opts = {}) {
if (this._destroyed || this._glLost || this._sampleRebinDisabled) return;
const targets = (this.gpuTraces || []).filter(
(g) => g.tier === "density" && g.sampleOverlay && g.sampleOverlay._cpu
);
if (!targets.length) return;
const seq = opts.seq ?? ++this.seq;
const view = { ...viewOverride };
clearTimeout(this._rebinTimer);
this._rebinTimer = setTimeout(() => {
if (this._destroyed || seq !== this.seq) return;
for (const g of targets) this._requestSampleRebin(g, view, seq);
}, opts.delay ?? 120);
},
_requestSampleRebin(g, view, seq) {
if (!g._homeDensity) g._homeDensity = g.density;
const v0 = this.view0;
const ex = Math.max(Math.abs(v0.x1 - v0.x0), 1e-300) * 1e-9;
const ey = Math.max(Math.abs(v0.y1 - v0.y0), 1e-300) * 1e-9;
const atHome =
Math.min(view.x0, view.x1) <= v0.x0 + ex && Math.max(view.x0, view.x1) >= v0.x1 - ex &&
Math.min(view.y0, view.y1) <= v0.y0 + ey && Math.max(view.y0, view.y1) >= v0.y1 - ey;
if (atHome) {
if (g.density !== g._homeDensity) {
const hd = g._homeDensity;
this._applySampleRebinGrid(g, {
...hd,
tex: this._uploadGrid(hd.grid, hd.w, hd.h, hd.normMax || hd.max || 1),
}, false);
}
return;
}
if (this._sampleRebinDisabled) return;
if (!this._rebinWorker) {
this._rebinWorker = fcCreateRebinWorker();
if (!this._rebinWorker) {
this._sampleRebinDisabled = true;
return;
}
this._rebinWorker.onmessage = (e) => this._onRebinResult(e.data);
this._rebinInit = new Set();
}
if (!this._rebinInit.has(g.trace.id)) {
const cpu = g.sampleOverlay._cpu;
const n = Math.min(cpu.x.length, cpu.y.length);
const xs = new Float64Array(n);
const ys = new Float64Array(n);
for (let i = 0; i < n; i++) {
xs[i] = this._decodeValue(cpu.x, cpu.xMeta, i);
ys[i] = this._decodeValue(cpu.y, cpu.yMeta, i);
}
this._rebinWorker.postMessage(
{ type: "init", trace: g.trace.id, x: xs.buffer, y: ys.buffer },
[xs.buffer, ys.buffer]
);
this._rebinInit.add(g.trace.id);
}
this._rebinWorker.postMessage({
type: "rebin", trace: g.trace.id, seq,
x0: Math.min(view.x0, view.x1), x1: Math.max(view.x0, view.x1),
y0: Math.min(view.y0, view.y1), y1: Math.max(view.y0, view.y1),
w: Math.max(16, Math.min(2048, Math.round(this.plot.w))),
h: Math.max(16, Math.min(2048, Math.round(this.plot.h))),
});
},
_onRebinResult(msg) {
if (this._destroyed || this._glLost || !msg || msg.type !== "grid" || msg.seq !== this.seq) return;
const g = this.gpuTraces.find((t) => t.trace.id === msg.trace && t.tier === "density");
if (!g) return;
const grid = new Float32Array(msg.grid);
this._applySampleRebinGrid(g, {
w: msg.w, h: msg.h, max: msg.max, normMax: msg.max,
colormap: g.density.colormap,
xRange: [msg.x0, msg.x1], yRange: [msg.y0, msg.y1],
grid,
tex: this._uploadGrid(grid, msg.w, msg.h, msg.max || 1),
lut: g.density.lut,
}, true);
},
_applySampleRebinGrid(g, density, rebinned) {
g.prevDensity = g.density;
g._densityFadeStart = this._now();
g.densityNormMax = density.normMax || density.max;
g.density = density;
g._sampleRebinned = !!rebinned;
lodRememberDensity(this, g, g.density);
this._refreshReductionBadges();
this.draw();
},
_applyAppend(msg, buffers) {
const spec = msg.spec;
const blobRaw = buffers && buffers[0];
if (!spec || !blobRaw || !spec.traces) return;
const blob = bytesToArrayBuffer(blobRaw);
const spanEps = (lo, hi) => Math.max(Math.abs(hi - lo), 1e-300) * 1e-9;
const ex = spanEps(this.view0.x0, this.view0.x1);
const ey = spanEps(this.view0.y0, this.view0.y1);
const atHome =
Math.abs(this.view.x0 - this.view0.x0) <= ex && Math.abs(this.view.x1 - this.view0.x1) <= ex &&
Math.abs(this.view.y0 - this.view0.y0) <= ey && Math.abs(this.view.y1 - this.view0.y1) <= ey;
const pinnedRight = !atHome && Math.abs(this.view.x1 - this.view0.x1) <= ex;
this.spec = spec;
this.axes = this._normalizeAxes(spec);
this._payload = blob;
this.view0 = {
x0: spec.x_axis.range[0], x1: spec.x_axis.range[1],
y0: spec.y_axis.range[0], y1: spec.y_axis.range[1],
};
if (atHome) {
this.view = { ...this.view0 };
} else if (pinnedRight) {
const w = this.view.x1 - this.view.x0;
this.view = { ...this.view, x1: this.view0.x1, x0: this.view0.x1 - w };
}
if (this._glLost || !this.gl) return;
const texSeen = new Set();
for (const id of msg.affected || []) {
const i = this.gpuTraces.findIndex((g) => g.trace.id === id);
const ts = spec.traces.find((t) => t.id === id);
if (i < 0 || !ts) continue;
this._destroyTraceResources(this.gpuTraces[i], texSeen);
this.gpuTraces[i] = this._buildTrace(blob, ts);
}
this._pickable = this.gpuTraces.some(
(g) => markOf(g.trace.kind).pointPick && (g.tier !== "density" || g.drill));
if (this._pickable && !this.pickFbo) this._initPickTarget();
this._scheduleViewRequest(this.view, { delay: 0 });
this.draw();
},
_onKernelMsg(msg, buffers) {
if (this._destroyed) return;
if (!msg) return;
if (this._glLost && msg.type !== "append" && msg.type !== "pick_result") return;
if (msg.type === "tier_update") {
if (msg.seq !== this.seq) return;
for (const upd of msg.traces) {
const g = this.gpuTraces.find((t) => t.trace.id === upd.id);
if (!g) continue;
const gl = this.gl;
const xArr = this._asF32(buffers[upd.x.buf]);
const yArr = this._asF32(buffers[upd.y.buf]);
const bArr = upd.base && g.baseBuf ? this._asF32(buffers[upd.base.buf]) : null;
let n = Math.min(upd.x.len, upd.y.len);
if (bArr) n = Math.min(n, upd.base.len);
const sm = this._smoothArrays(g.trace, xArr, yArr, bArr, n);
const src = sm || { x: xArr, y: yArr, n };
const st = this._stepArrays(g.trace, src.x, src.y, src.n);
gl.bindBuffer(gl.ARRAY_BUFFER, g.xBuf);
gl.bufferData(gl.ARRAY_BUFFER, st ? st.x : src.x, gl.STATIC_DRAW);
gl.bindBuffer(gl.ARRAY_BUFFER, g.yBuf);
gl.bufferData(gl.ARRAY_BUFFER, st ? st.y : src.y, gl.STATIC_DRAW);
g.xMeta = { ...g.xMeta, offset: upd.x.offset, scale: upd.x.scale };
g.yMeta = { ...g.yMeta, offset: upd.y.offset, scale: upd.y.scale };
g._dashX = st ? st.x : src.x;
g._dashY = st ? st.y : src.y;
if (bArr) {
gl.bindBuffer(gl.ARRAY_BUFFER, g.baseBuf);
gl.bufferData(gl.ARRAY_BUFFER, sm ? sm.extra : bArr, gl.STATIC_DRAW);
g.baseMeta = { ...g.baseMeta, offset: upd.base.offset, scale: upd.base.scale };
}
g.n = st ? st.n : src.n;
}
this.draw();
} else if (msg.type === "density_update") {
if (msg.seq !== undefined && msg.seq !== this.seq) return;
const densityTraces = msg.traces || [];
const pendingTraceIds = new Set(densityTraces.map((upd) => Number(upd.id)));
if (pendingTraceIds.size === 0 && msg.trace !== undefined) {
pendingTraceIds.add(Number(msg.trace));
}
const clearAllPending = pendingTraceIds.size === 0 && msg.stale;
const clearPending = (g) => {
if (msg.seq !== undefined && g._lodPendingSeq !== msg.seq) return;
g._lodPendingView = null;
g._lodPendingSeq = null;
g._lodPendingAt = null;
};
if (pendingTraceIds.size || clearAllPending) {
for (const g of this.gpuTraces) {
if (g.tier !== "density") continue;
if (!clearAllPending && !pendingTraceIds.has(g.trace.id)) continue;
clearPending(g);
}
}
for (const upd of densityTraces) {
const g = this.gpuTraces.find((t) => t.trace.id === upd.id && t.tier === "density");
if (!g) continue;
clearPending(g);
if (upd.mode === "points") { this._applyDrill(g, upd, buffers); continue; }
lodApplyDensityUpdate(this, g, upd, buffers);
}
this._pickable = this.gpuTraces.some(
(t) => markOf(t.trace.kind).pointPick && (t.tier !== "density" || t.drill));
if (this._pickable && !this.pickFbo) this._initPickTarget();
this.draw();
} else if (msg.type === "append") {
this._applyAppend(msg, buffers);
} else if (msg.type === "pick_result") {
if (!msg.row) { this.tooltip.style.display = "none"; return; }
this._lastRow = msg.row;
const xy = this._lastHoverXY;
if (xy) this._renderTooltip(msg.row, xy.clientX, xy.clientY);
if (this._interactionFlag("hover")) {
this._dispatchChartEvent("hover", {
row: msg.row,
trace: msg.row.trace,
index: msg.row.index,
exact: true,
view: this._eventView("hover"),
});
}
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
const pg = g.tier === "density" ? g.drill : g;
if (!pg || !pg.n) continue;
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
if (this._interactionFlag("select", true)) {
this._dispatchChartEvent("select", {
total: this._selectionCount,
view: this._eventView("select"),
});
}
}
},
_applyDrill(g, upd, buffers) {
lodApplyDrill(this, g, upd, buffers);
},
_dropDrill(g) {
lodDropDrill(this, g);
},
_viewInside(win) {
if (!win) return false;
const { x0, x1, y0, y1 } = this.view;
const ex = Math.abs(x1 - x0) * 1e-4, ey = Math.abs(y1 - y0) * 1e-4;
const vx0 = Math.min(x0, x1), vx1 = Math.max(x0, x1);
const vy0 = Math.min(y0, y1), vy1 = Math.max(y0, y1);
const wx0 = Math.min(win.x0, win.x1), wx1 = Math.max(win.x0, win.x1);
const wy0 = Math.min(win.y0, win.y1), wy1 = Math.max(win.y0, win.y1);
return vx0 >= wx0 - ex && vx1 <= wx1 + ex && vy0 >= wy0 - ey && vy1 <= wy1 + ey;
},
_viewInsideRange(xRange, yRange) {
if (!xRange || !yRange) return false;
return this._viewInside({ x0: xRange[0], x1: xRange[1], y0: yRange[0], y1: yRange[1] });
},
});
const RECT_MARK = {
build: (view, g, t, buffer) => view._buildRectMark(g, t, buffer),
draw: (view, g) => {
const [x0, x1] = view._axisRange(g.xAxis);
const [y0, y1] = view._axisRange(g.yAxis);
const edgePad = g.trace.kind === "histogram"
? [0, 0, view._edgePadForValue(0, y0, y1, view.canvas.height), 0]
: [0, 0, 0, 0];
view._drawRects(
g,
view._map(g.x0Meta, x0, x1, g.xAxis),
view._map(g.x1Meta, x0, x1, g.xAxis),
view._map(g.y0Meta, y0, y1, g.yAxis),
view._map(g.y1Meta, y0, y1, g.yAxis),
edgePad
);
},
refreshColor: (view, g) => {
if (!g.colorMode) g.color = parseColor(view.root, g.trace.style.color, g.color);
view._rectMarkStyleGpu(g, g.trace);
},
};
const BAR_MARK = {
build: (view, g, t, buffer) => view._buildBarMark(g, t, buffer),
draw: (view, g) => {
if (!g.trace.bar) {
RECT_MARK.draw(view, g);
return;
}
const horizontal = g.orientation === 1;
const pAxis = horizontal ? g.yAxis : g.xAxis;
const vAxis = horizontal ? g.xAxis : g.yAxis;
const [p0, p1] = view._axisRange(pAxis);
const [v0, v1] = view._axisRange(vAxis);
const pmap = view._map(g.posMeta, p0, p1, pAxis);
const v1map = view._map(g.value1Meta, v0, v1, vAxis);
const v0map = g.value0Mode === 1
? view._map(g.value0Meta, v0, v1, vAxis)
: null;
const v0Const = g.value0Mode === 0
? view._mapConst(g.value0Const, v0, v1, vAxis)
: null;
const v0EdgePad = g.value0Mode === 0
? view._edgePadForValue(
g.value0Const,
v0,
v1,
horizontal ? view.canvas.width : view.canvas.height
)
: 0;
view._drawBars(g, pmap, v1map, v0map, v0Const, v0EdgePad);
},
refreshColor: (view, g) => {
if (!g.colorMode) g.color = parseColor(view.root, g.trace.style.color, g.color);
view._rectMarkStyleGpu(g, g.trace);
},
};
const SEGMENT_MARK = {
build: (view, g, t, buffer) => view._buildSegmentMark(g, t, buffer),
draw: (view, g) => {
const [x0, x1] = view._axisRange(g.xAxis);
const [y0, y1] = view._axisRange(g.yAxis);
view._drawSegments(
g,
view._map(g.x0Meta, x0, x1, g.xAxis),
view._map(g.y0Meta, y0, y1, g.yAxis),
);
},
refreshColor: (view, g) => {
if (!g.colorMode) g.color = parseColor(view.root, g.trace.style.color, g.color);
},
};
const AREA_MARK = {
build: (view, g, t, buffer) => view._buildAreaMark(g, t, buffer),
draw: (view, g) => {
const [x0, x1] = view._axisRange(g.xAxis);
const [y0, y1] = view._axisRange(g.yAxis);
const xm = view._map(g.xMeta, x0, x1, g.xAxis);
const ym = view._map(g.yMeta, y0, y1, g.yAxis);
view._drawArea(g, xm, ym, view._map(g.baseMeta, y0, y1, g.yAxis));
if ((g.trace.style.line_width ?? 0) > 0) {
view._drawLine(g, xm, ym, g.lineColor, g.trace.style.line_width, g.trace.style.line_opacity ?? 1);
}
},
refreshColor: (view, g) => {
g.color = parseColor(view.root, g.trace.style.color, g.color);
g.lineColor = parseColor(view.root, g.trace.style.color, g.lineColor || g.color);
g.grad = view._resolveMarkFill(g.trace.style, g.color);
},
};
const MESH_MARK = {
build: (view, g, t, buffer) => view._buildMeshMark(g, t, buffer),
draw: (view, g) => {
const [x0, x1] = view._axisRange(g.xAxis);
const [y0, y1] = view._axisRange(g.yAxis);
view._drawMesh(g, view._map(g.x0Meta, x0, x1, g.xAxis), view._map(g.y0Meta, y0, y1, g.yAxis));
},
refreshColor: (view, g) => {
if (g.colorMode === 0 && g.trace.color) g.color = parseColor(view.root, g.trace.color.color, g.color);
const style = g.trace.style || {};
g.meshStroke = parseColor(view.root, style.stroke || "transparent", [0, 0, 0, 0]);
},
};
const MARK_KINDS = {
histogram: RECT_MARK,
box: RECT_MARK,
violin: RECT_MARK,
errorbar: SEGMENT_MARK,
stem: SEGMENT_MARK,
box_whisker: SEGMENT_MARK,
box_median: SEGMENT_MARK,
contour: SEGMENT_MARK,
segments: SEGMENT_MARK,
triangle_mesh: MESH_MARK,
error_band: AREA_MARK,
hexbin: {
build: (view, g, t, buffer) => view._buildMeshMark(g, t, buffer),
draw: (view, g) => {
const [x0, x1] = view._axisRange(g.xAxis);
const [y0, y1] = view._axisRange(g.yAxis);
view._drawMesh(g, view._map(g.x0Meta, x0, x1, g.xAxis), view._map(g.y0Meta, y0, y1, g.yAxis));
},
refreshColor: (view, g) => {
if (g.colorMode === 0 && g.trace.color) g.color = parseColor(view.root, g.trace.color.color, g.color);
const style = g.trace.style || {};
g.meshStroke = parseColor(view.root, style.stroke || "transparent", [0, 0, 0, 0]);
},
},
bar: BAR_MARK,
column: BAR_MARK,
heatmap: {
build: (view, g, t, buffer) => view._buildHeatmapMark(g, t, buffer),
draw: (view, g) => view._drawHeatmap(g),
},
scatter: {
build: (view, g, t, buffer) => view._buildScatterMark(g, t, buffer),
draw: (view, g) => {
const [x0, x1] = view._axisRange(g.xAxis);
const [y0, y1] = view._axisRange(g.yAxis);
view._drawPoints(g, view._map(g.xMeta, x0, x1, g.xAxis), view._map(g.yMeta, y0, y1, g.yAxis));
},
pointPick: true,
retainCpu: true,
refreshColor: (view, g) => {
if (g.colorMode === 0 && g.trace.color) {
g.color = parseColor(view.root, g.trace.color.color, g.color);
}
view._pointMarkStyle(g, g.trace);
},
},
line: {
build: (view, g, t, buffer) => view._buildLineMark(g, t, buffer),
draw: (view, g) => {
const [x0, x1] = view._axisRange(g.xAxis);
const [y0, y1] = view._axisRange(g.yAxis);
view._drawLine(g, view._map(g.xMeta, x0, x1, g.xAxis), view._map(g.yMeta, y0, y1, g.yAxis));
},
refreshColor: (view, g) => {
g.color = parseColor(view.root, g.trace.style.color, g.color);
},
},
area: AREA_MARK,
};
function markOf(kind) {
return MARK_KINDS[kind] || MARK_KINDS.scatter;
}
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
onMessage: (cb) => {
const handler = (content, buffers) => cb(content, buffers);
model.on("msg:custom", handler);
return () => model.off?.("msg:custom", handler);
},
};
const view = new ChartView(el, spec, buffer, comm);
return () => view.destroy();
}

function renderStandalone(el, spec, arrayBuffer) {
const buffer = bytesToArrayBuffer(arrayBuffer);
const view = new ChartView(el, spec, buffer, null);
const column = (idx) => view._columnView(buffer, spec.columns[idx]);
for (const g of view.gpuTraces) {
if (markOf(g.trace.kind).retainCpu && g.tier !== "density") {
g._cpu = {
x: column(g.trace.x),
y: column(g.trace.y),
xMeta: g.xMeta,
yMeta: g.yMeta,
};
if (g.trace.color && Number.isInteger(g.trace.color.buf)) {
g._cpu.color = column(g.trace.color.buf);
}
if (g.trace.size && Number.isInteger(g.trace.size.buf)) {
g._cpu.size = column(g.trace.size.buf);
}
}
}
return view;
}

window.xy = { render, renderStandalone, ChartView, MARK_KINDS, markOf };
})();
