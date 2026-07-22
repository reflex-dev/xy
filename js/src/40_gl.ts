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

// Fixed vertex-attribute slots, bound before linking so every program sees the
// same location for a given attribute name. This is what lets one VAO serve
// multiple programs over the same buffers (draw + pick), and turns all
// per-frame getAttribLocation lookups into compile-time constants. Names only
// need distinct slots *within* each program; the groups below are disjoint per
// shader (point: ax/ay + a_*; line/area: ax0..ab1; bar: a_pos/a_v1/a_v0;
// grid quad: a_corner). WebGL2 guarantees >= 16 attribs; the max used is 15.
export const ATTR_SLOTS = {
  ax: 0, ay: 1,
  ax0: 0, ax1: 1, ay0: 2, ay1: 3, ax2: 4, ay2: 5, ab0: 4, ab1: 5,
  a_pos: 0, a_v1: 1, a_v0: 2,
  a_corner: 0,
  a_cval: 6, a_sval: 7, a_sel: 8, a_dval: 9,
  a_len0: 10, a_len1: 11,
  a_dash0: 10, a_dashDir: 11,
  // Transition "previous-frame" positions and per-item style channels are
  // independent feature families that coexist in one program (point, bar), so
  // they must occupy disjoint slots. The style family is pinned to 12-15: it is
  // used across point/segment/mesh/rect/bar, whose fixed attributes already
  // span every slot 0-11. The transition family reuses lower slots those
  // programs leave free — 4/5 alias mesh ax2/ay2 & area ab0/ab1, 7/8 alias
  // a_sval/a_sel — none ever co-resident with a_prev* in the same program.
  a_prevx: 4, a_prevy: 5, a_prevx1: 7, a_prevy1: 8,
  a_rgba: 12, a_style: 13, a_stroke: 14, a_radius: 15,
};

export function makeProgram(gl, vs, fs) {
  const p = gl.createProgram();
  const vsh = compile(gl, gl.VERTEX_SHADER, vs);
  const fsh = compile(gl, gl.FRAGMENT_SHADER, fs);
  gl.attachShader(p, vsh);
  gl.attachShader(p, fsh);
  for (const [name, slot] of Object.entries(ATTR_SLOTS)) {
    gl.bindAttribLocation(p, slot, name); // no-op for names a shader lacks
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
  // Uniform-location cache (renderer audit R1): draw paths look locations up
  // by name every frame; memoize per program so each name hits the driver once.
  p._u = Object.create(null);
  return p;
}

export function uniformOf(gl, prog, name) {
  let loc = prog._u[name];
  if (loc === undefined) {
    loc = gl.getUniformLocation(prog, name);
    prog._u[name] = loc;
  }
  return loc;
}

// Points: per-vertex position, plus optional per-vertex color scalar (a_cval)
// and size scalar (a_sval). Color mode selects how the LUT is sampled; the LUT
// is a 256×1 texture (colormap or cycled palette). Size mode maps a_sval into a
// px range. SDF-antialiased in the fragment stage.
const AXIS_GLSL = `
float xyDecode(float encoded, vec2 meta) {
  return encoded / max(abs(meta.y), 1e-30) + meta.x;
}
float xyAxisCoord(float encoded, vec2 meta, int mode) {
  float value = xyDecode(encoded, meta);
  if (mode == 1) return value > 0.0 ? log(value) / log(10.0) : -1e30;
  return value;
}
float xyMap(float encoded, vec2 map, vec2 meta, int mode) {
  return xyAxisCoord(encoded, meta, mode) * map.x + map.y;
}
float xyViewCoord(float value, int mode) {
  if (mode == 1) return value > 0.0 ? log(value) / log(10.0) : -1e30;
  return value;
}
float xyViewValue(float coord, int mode) {
  if (mode == 1) return pow(10.0, coord);
  return coord;
}
`;

export const POINT_VS = `#version 300 es
in float ax; in float ay; in float a_prevx; in float a_prevy;
in float a_cval; in float a_sval; in float a_sel; in float a_dval;
in vec4 a_rgba; in vec4 a_style; in vec4 a_stroke;
uniform vec2 u_xmap; uniform vec2 u_ymap;
uniform vec2 u_xmeta; uniform vec2 u_ymeta; uniform int u_xmode; uniform int u_ymode;
uniform float u_size; uniform int u_sizeMode; uniform vec2 u_sizeRange;
uniform int u_colorMode; uniform float u_dpr; uniform int u_selActive;
uniform float u_selectedOpacity; uniform float u_unselectedOpacity;
uniform float u_transitionProgress; uniform int u_transitionActive;
out float v_lutCoord; out float v_dim; out float v_dval; out float v_ptSize; out float v_sel;
out vec4 v_rgba; out vec4 v_style; out vec4 v_stroke;
${AXIS_GLSL}
void main() {
  float x = u_transitionActive == 1 ? mix(a_prevx, ax, u_transitionProgress) : ax;
  float y = u_transitionActive == 1 ? mix(a_prevy, ay, u_transitionProgress) : ay;
  gl_Position = vec4(xyMap(x, u_xmap, u_xmeta, u_xmode), xyMap(y, u_ymap, u_ymeta, u_ymode), 0.0, 1.0);
  float sz = u_sizeMode == 1 ? mix(u_sizeRange.x, u_sizeRange.y, a_sval) : u_size;
  gl_PointSize = sz * u_dpr;
  v_ptSize = sz * u_dpr;
  v_sel = a_sel;
  v_rgba = a_rgba;
  v_style = a_style;
  v_stroke = a_stroke;
  // continuous: coord = value in [0,1]; categorical: center of texel a_cval.
  v_lutCoord = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
  // Local log-density LUT coord (drill handoff, §5): lets freshly drilled
  // points wear the density colormap so the texture->points swap is seamless.
  v_dval = a_dval;
  // Unselected marks dim when a selection is active (§34 selected/unselected styling).
  v_dim = u_selActive == 1 ? mix(u_unselectedOpacity, u_selectedOpacity, step(0.5, a_sel)) : 1.0;
}`;

// Marker signed distance in gl_PointCoord-centered space (d in [-0.5,0.5]),
// <0 inside, 0 at the boundary. Symbols match the annotation markers plus
// triangle. With u_symbol=0 and no stroke this reduces to the old circle.
const MARKER_SDF_GLSL = `
float xySegmentDistance(vec2 p, vec2 a, vec2 b) {
  vec2 e = b - a;
  return length(p - a - e * clamp(dot(p - a, e) / dot(e, e), 0.0, 1.0));
}
float xyTriangleDistance(vec2 p, vec2 a, vec2 b, vec2 c) {
  float dist = min(xySegmentDistance(p, a, b),
                   min(xySegmentDistance(p, b, c), xySegmentDistance(p, c, a)));
  float c0 = (b.x-a.x)*(p.y-a.y) - (b.y-a.y)*(p.x-a.x);
  float c1 = (c.x-b.x)*(p.y-b.y) - (c.y-b.y)*(p.x-b.x);
  float c2 = (a.x-c.x)*(p.y-c.y) - (a.y-c.y)*(p.x-c.x);
  bool inside = (c0 >= 0.0 && c1 >= 0.0 && c2 >= 0.0) ||
                (c0 <= 0.0 && c1 <= 0.0 && c2 <= 0.0);
  return inside ? -dist : dist;
}
float xyPentagonDistance(vec2 p) {
  // Path.unit_regular_polygon(5), then Matplotlib's 0.5 marker transform.
  vec2 a = vec2(0.0, -0.5);
  vec2 b = vec2(-0.475528258, -0.154508497);
  vec2 c = vec2(-0.293892626, 0.404508497);
  vec2 d = vec2(0.293892626, 0.404508497);
  vec2 e = vec2(0.475528258, -0.154508497);
  float dist = min(min(xySegmentDistance(p, a, b), xySegmentDistance(p, b, c)),
                   min(min(xySegmentDistance(p, c, d), xySegmentDistance(p, d, e)),
                       xySegmentDistance(p, e, a)));
  float c0 = (b.x-a.x)*(p.y-a.y) - (b.y-a.y)*(p.x-a.x);
  float c1 = (c.x-b.x)*(p.y-b.y) - (c.y-b.y)*(p.x-b.x);
  float c2 = (d.x-c.x)*(p.y-c.y) - (d.y-c.y)*(p.x-c.x);
  float c3 = (e.x-d.x)*(p.y-d.y) - (e.y-d.y)*(p.x-d.x);
  float c4 = (a.x-e.x)*(p.y-e.y) - (a.y-e.y)*(p.x-e.x);
  bool inside = (c0 >= 0.0 && c1 >= 0.0 && c2 >= 0.0 && c3 >= 0.0 && c4 >= 0.0) ||
                (c0 <= 0.0 && c1 <= 0.0 && c2 <= 0.0 && c3 <= 0.0 && c4 <= 0.0);
  return inside ? -dist : dist;
}
float xyMarkerSdf(vec2 d, int shape) {
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
  if (shape == 6) return xyPentagonDistance(d);                      // exact regular pentagon
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
    return xyTriangleDistance(q, vec2(0.0, -0.5), vec2(-0.5, 0.5), vec2(0.5, 0.5));
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

export const POINT_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_color; uniform int u_colorMode; uniform sampler2D u_lut; uniform float u_opacity;
uniform sampler2D u_dlut; uniform float u_dblend;
uniform int u_symbol; uniform vec4 u_ptStroke; uniform float u_ptStrokeWidth; uniform int u_ptStrokeFace;
uniform int u_strokeMode; uniform float u_strokeOpacity;
uniform int u_selActive; uniform vec4 u_selColor; uniform vec4 u_unselColor;
in float v_lutCoord; in float v_dim; in float v_dval; in float v_ptSize; in float v_sel;
in vec4 v_rgba; in vec4 v_style; in vec4 v_stroke;
out vec4 outColor;
${MARKER_SDF_GLSL}
void main() {
  vec2 d = gl_PointCoord - 0.5;
  float sd;
  int symbol = v_style.w >= 0.0 ? int(v_style.w + 0.5) : u_symbol;
  bool lineMarker = symbol == 15 || symbol == 16;
  if (lineMarker) {
    vec2 q = symbol == 16 ? vec2(d.x + d.y, d.y - d.x) * 0.707106781 : d;
    float itemStrokeWidth = v_style.z >= 0.0 ? v_style.z : u_ptStrokeWidth;
    float halfWidth = max(itemStrokeWidth, 1.0) / (2.0 * max(v_ptSize, 1.0));
    vec2 a = abs(q);
    sd = min(max(a.x - 0.5, a.y - halfWidth), max(a.y - 0.5, a.x - halfWidth));
  } else {
    // Scalar-only equivalent: xyMarkerSdf(d, u_symbol). The resolved symbol
    // also permits a per-item glyph override from v_style.w.
    sd = xyMarkerSdf(d, symbol);
  }
  float aa = fwidth(sd) + 1e-4;
  float shapeCov = clamp(0.5 - sd / aa, 0.0, 1.0);
  if (shapeCov <= 0.001) discard;
  vec4 paint = u_colorMode == 3 ? v_rgba : (u_colorMode == 0 ? u_color : vec4(texture(u_lut, vec2(clamp(v_lutCoord, 0.0, 1.0), 0.5)).rgb, 1.0));
  vec3 rgb = paint.rgb;
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
  float intrinsicAlpha = paint.a;
  float fillAlpha = (v_style.y >= 0.0 ? v_style.y : intrinsicAlpha) * v_style.x * u_opacity;
  vec4 px = vec4(rgb * fillAlpha, fillAlpha);   // premultiplied fill
  // Uniform (u_ptStroke) and per-item (v_stroke) stroke paint ship straight
  // alpha and go through the same artist-alpha/opacity stack, so a scalar
  // CSS edge fades under alpha overrides exactly like SVG/PNG export.
  vec4 strokeSrc = u_strokeMode == 1 ? v_stroke : u_ptStroke;
  float strokeAlpha = (v_style.y >= 0.0 ? v_style.y : strokeSrc.a) * v_style.x * u_strokeOpacity;
  vec4 strokePx = u_ptStrokeFace == 1 ? px : vec4(strokeSrc.rgb * strokeAlpha, strokeAlpha);
  if (lineMarker) {
    outColor = strokePx * (shapeCov * v_dim);
    return;
  }
  float itemStrokeWidth = v_style.z >= 0.0 ? v_style.z : u_ptStrokeWidth;
  if (itemStrokeWidth > 0.0) {
    float sw = itemStrokeWidth / max(v_ptSize, 1.0);   // px -> gl_PointCoord units
    // The supplied point size includes the edge.  Recover Matplotlib's path
    // boundary half a stroke inside it, then source-over the centered stroke.
    float pathCov = clamp(0.5 - (sd + sw * 0.5) / aa, 0.0, 1.0);
    float innerCov = clamp(0.5 - (sd + sw) / aa, 0.0, 1.0);
    float strokeCov = max(shapeCov - innerCov, 0.0);
    vec4 fillLayer = px * pathCov;
    vec4 strokeLayer = strokePx * strokeCov;
    px = strokeLayer + fillLayer * (1.0 - strokeLayer.a);
    outColor = px * v_dim;
    return;
  }
  outColor = px * (shapeCov * v_dim);
}`;

// Default constant circle: the dominant small/medium scatter path deserves a
// shader that does only its visual contract. Rich color/size/selection/drill
// and stroked/symbol markers keep POINT_VS/POINT_FS below. Keeping this
// specialization separate avoids dynamic feature branches and texture state
// on software GL while producing the same circle SDF and premultiplied color.
export const POINT_SIMPLE_VS = `#version 300 es
in float ax; in float ay; in float a_prevx; in float a_prevy;
uniform vec2 u_xmap; uniform vec2 u_ymap;
uniform vec2 u_xmeta; uniform vec2 u_ymeta; uniform int u_xmode; uniform int u_ymode;
uniform float u_size; uniform float u_dpr;
uniform float u_transitionProgress; uniform int u_transitionActive;
${AXIS_GLSL}
void main() {
  float x = u_transitionActive == 1 ? mix(a_prevx, ax, u_transitionProgress) : ax;
  float y = u_transitionActive == 1 ? mix(a_prevy, ay, u_transitionProgress) : ay;
  gl_Position = vec4(xyMap(x, u_xmap, u_xmeta, u_xmode), xyMap(y, u_ymap, u_ymeta, u_ymode), 0.0, 1.0);
  gl_PointSize = u_size * u_dpr;
}`;

export const POINT_SIMPLE_FS = `#version 300 es
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

// Picking: same geometry + size, outputs an encoded ID so a single readPixels
// resolves which point is under the cursor (§17). Rerun's R-channel-ID-texture
// idea, RGBA8 variant. The ID is GLOBAL across pick-drawn traces: each trace
// draw sets `u_pick_base` to 1 + the points drawn before it, and the fragment
// writes the full 32-bit `base + gl_VertexID` across RGBA; all-zero RGBA is
// the background sentinel (bases start at 1), and `_pickAt` maps the value
// back to (trace, index) by range lookup. The earlier 24-bit-index +
// 8-bit-slot split aliased trace slot 255 onto 254 (the +1 sentinel shift
// saturated the u8 alpha channel) and wrapped point indices above 2^24; one
// global id space has neither limit — capacity is 2^31-1 total pickable
// points (GLSL highp int is signed), far beyond what GPU memory admits.
export const PICK_VS = `#version 300 es
in float ax; in float ay; in float a_prevx; in float a_prevy; in float a_sval;
uniform vec2 u_xmap; uniform vec2 u_ymap;
uniform vec2 u_xmeta; uniform vec2 u_ymeta; uniform int u_xmode; uniform int u_ymode;
uniform float u_size; uniform int u_sizeMode; uniform vec2 u_sizeRange; uniform float u_dpr;
uniform float u_transitionProgress; uniform int u_transitionActive;
flat out int v_id;
${AXIS_GLSL}
void main() {
  float x = u_transitionActive == 1 ? mix(a_prevx, ax, u_transitionProgress) : ax;
  float y = u_transitionActive == 1 ? mix(a_prevy, ay, u_transitionProgress) : ay;
  gl_Position = vec4(xyMap(x, u_xmap, u_xmeta, u_xmode), xyMap(y, u_ymap, u_ymeta, u_ymode), 0.0, 1.0);
  float sz = u_sizeMode == 1 ? mix(u_sizeRange.x, u_sizeRange.y, a_sval) : u_size;
  gl_PointSize = max(sz, 6.0) * u_dpr; // enlarge hit target
  v_id = gl_VertexID;
}`;

export const PICK_FS = `#version 300 es
precision highp float; precision highp int;
uniform int u_pick_base;
flat in int v_id;
out vec4 outColor;
void main() {
  vec2 d = gl_PointCoord - 0.5;
  if (length(d) > 0.5) discard;
  int id = u_pick_base + v_id;
  outColor = vec4(
    float(id & 255) / 255.0,
    float((id >> 8) & 255) / 255.0,
    float((id >> 16) & 255) / 255.0,
    float((id >> 24) & 255) / 255.0
  );
}`;

// Shared grid-texture vertex stage (density Tier 2 + heatmap): a fullscreen
// quad; each fragment reconstructs its data-space coordinate from the view
// range so the fragment shader can sample the grid texture (§5, §F6). Data
// outside the grid range is transparent — a stale grid stays correctly
// positioned during pan until the re-bin arrives (§17). The two consumers
// differ only in their fragment stage (log-density alpha ramp vs byte-
// quantized heatmap values).
export const GRID_VS = `#version 300 es
in vec2 a_corner;
uniform vec4 u_view; // x0,x1,y0,y1
uniform int u_xmode; uniform int u_ymode;
out vec2 v_data;
${AXIS_GLSL}
void main() {
  gl_Position = vec4(a_corner * 2.0 - 1.0, 0.0, 1.0);
  float x = mix(xyViewCoord(u_view.x, u_xmode), xyViewCoord(u_view.y, u_xmode), a_corner.x);
  float y = mix(xyViewCoord(u_view.z, u_ymode), xyViewCoord(u_view.w, u_ymode), a_corner.y);
  v_data = vec2(xyViewValue(x, u_xmode), xyViewValue(y, u_ymode));
}`;

export const DENSITY_FS = `#version 300 es
precision highp float;
uniform sampler2D u_grid; uniform sampler2D u_lut;
uniform vec4 u_gridRange; // gx0,gx1,gy0,gy1
uniform float u_opacity; uniform vec4 u_color; uniform int u_constantColor;
in vec2 v_data;
out vec4 outColor;
void main() {
  vec2 uv = vec2((v_data.x - u_gridRange.x) / (u_gridRange.y - u_gridRange.x),
                 (v_data.y - u_gridRange.z) / (u_gridRange.w - u_gridRange.z));
  if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) discard;
  float t = texture(u_grid, uv).r;
  if (t <= 0.0) discard;
  vec4 paint = u_constantColor == 1
    ? u_color
    : texture(u_lut, vec2(clamp(t, 0.0, 1.0), 0.5));
  vec3 rgb = paint.rgb;
  float alpha = u_opacity * paint.a * clamp(t * 1.35, 0.0, 1.0);
  if (alpha <= 0.01) discard;
  outColor = vec4(rgb * alpha, alpha);
}`;

// Heatmap grid: a regular value matrix as one R8 texture. Byte 0 means missing
// (transparent); bytes 1..255 map back to normalized values [0,1]. Vertex
// stage is the shared GRID_VS above.
export const HEATMAP_FS = `#version 300 es
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

export const LINE_VS = `#version 300 es
in float ax0; in float ay0; in float ax1; in float ay1;
in float a_prevx; in float a_prevy; in float a_prevx1; in float a_prevy1;
uniform vec2 u_xmap; uniform vec2 u_ymap; uniform vec2 u_res; uniform float u_width;
uniform int u_colorMode;
uniform float u_transitionProgress; uniform int u_transitionActive;
uniform float u_revealProgress; uniform float u_revealSegments;
uniform vec2 u_xmeta; uniform vec2 u_ymeta; uniform int u_xmode; uniform int u_ymode;
in float a_len0; in float a_len1;
out float v_off; out float v_dash;
const vec2 corners[4] = vec2[4](vec2(0.,-1.), vec2(0.,1.), vec2(1.,-1.), vec2(1.,1.));
${AXIS_GLSL}
void main() {
  float px0 = u_transitionActive == 1 ? mix(a_prevx, ax0, u_transitionProgress) : ax0;
  float py0 = u_transitionActive == 1 ? mix(a_prevy, ay0, u_transitionProgress) : ay0;
  float px1 = u_transitionActive == 1 ? mix(a_prevx1, ax1, u_transitionProgress) : ax1;
  float py1 = u_transitionActive == 1 ? mix(a_prevy1, ay1, u_transitionProgress) : ay1;
  vec2 p0 = vec2(xyMap(px0, u_xmap, u_xmeta, u_xmode), xyMap(py0, u_ymap, u_ymeta, u_ymode));
  vec2 p1 = vec2(xyMap(px1, u_xmap, u_xmeta, u_xmode), xyMap(py1, u_ymap, u_ymeta, u_ymode));
  float reveal = clamp(u_revealProgress * u_revealSegments - float(gl_InstanceID), 0.0, 1.0);
  p1 = mix(p0, p1, reveal);
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
  v_dash = mix(a_len0, mix(a_len0, a_len1, reveal), c.x);
}`;

export const LINE_FS = `#version 300 es
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

// Segment marks (errorbar/stem/box whiskers/contour isolines): independent
// endpoint pairs with per-column axis metas and an optional per-segment LUT
// color. A separate program keeps the polyline path (LINE_VS/LINE_FS) free of
// the extra meta uniforms and the sampler on its per-frame draw path.
export const SEGMENT_VS = `#version 300 es
in float ax0; in float ay0; in float ax1; in float ay1; in float a_cval; in vec4 a_rgba; in vec4 a_style;
in float a_dash0; in float a_dashDir;
uniform vec2 u_xmap; uniform vec2 u_ymap; uniform vec2 u_res; uniform float u_width;
uniform float u_animationProgress;
uniform int u_colorMode;
uniform vec2 u_x0meta; uniform vec2 u_x1meta; uniform vec2 u_y0meta; uniform vec2 u_y1meta;
uniform int u_x0mode; uniform int u_x1mode; uniform int u_y0mode; uniform int u_y1mode;
out float v_off; out float v_cval; out float v_dash; out vec4 v_rgba; out vec4 v_style;
const vec2 corners[4] = vec2[4](vec2(0.,-1.), vec2(0.,1.), vec2(1.,-1.), vec2(1.,1.));
${AXIS_GLSL}
void main() {
  vec2 p0 = vec2(xyMap(ax0, u_xmap, u_x0meta, u_x0mode), xyMap(ay0, u_ymap, u_y0meta, u_y0mode));
  vec2 p1 = vec2(xyMap(ax1, u_xmap, u_x1meta, u_x1mode), xyMap(ay1, u_ymap, u_y1meta, u_y1mode));
  vec2 center = (p0 + p1) * 0.5;
  p0 = mix(center, p0, u_animationProgress);
  p1 = mix(center, p1, u_animationProgress);
  vec2 pix0 = (p0 * 0.5 + 0.5) * u_res;
  vec2 pix1 = (p1 * 0.5 + 0.5) * u_res;
  vec2 dir = pix1 - pix0;
  float len = max(length(dir), 1e-6);
  dir /= len;
  vec2 n = vec2(-dir.y, dir.x);
  vec2 c = corners[gl_VertexID];
  float itemWidth = a_style.z >= 0.0 ? a_style.z : u_width;
  float half_w = itemWidth * 0.5 + 0.5;
  vec2 pos = mix(pix0, pix1, c.x) + dir * (c.x * 2.0 - 1.0) * 0.5 + n * c.y * half_w;
  gl_Position = vec4(pos / u_res * 2.0 - 1.0, 0.0, 1.0);
  v_off = c.y * half_w;
  v_cval = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
  v_dash = a_dash0 + c.x * len * a_dashDir;
  v_rgba = a_rgba; v_style = a_style;
}`;

export const SEGMENT_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_color; uniform float u_width; uniform int u_colorMode; uniform sampler2D u_lut; uniform float u_opacity;
uniform int u_dashCount; uniform float u_dashArr[8]; uniform float u_dashPeriod;
in float v_off; in float v_cval; in float v_dash; in vec4 v_rgba; in vec4 v_style;
out vec4 outColor;
void main() {
  float itemWidth = v_style.z >= 0.0 ? v_style.z : u_width;
  float half_w = itemWidth * 0.5;
  vec4 paint = u_colorMode == 3 ? v_rgba : (u_colorMode != 0 ? vec4(texture(u_lut, vec2(clamp(v_cval, 0.0, 1.0), 0.5)).rgb, 1.0) : u_color);
  vec3 rgb = paint.rgb;
  float paintAlpha = (v_style.y >= 0.0 ? v_style.y : paint.a) * v_style.x * u_opacity;
  float alpha = (1.0 - smoothstep(half_w - 0.5, half_w + 0.5, abs(v_off))) * paintAlpha;
  if (u_dashCount > 0) {
    float m = mod(v_dash, u_dashPeriod);
    float acc = 0.0;
    float on = 0.0;
    for (int i = 0; i < 8; i++) {
      if (i >= u_dashCount) break;
      float next = acc + u_dashArr[i];
      if (m < next) { on = (i % 2 == 0) ? 1.0 : 0.0; break; }
      acc = next;
    }
    alpha *= on;
  }
  if (alpha <= 0.001) discard;
  outColor = vec4(rgb * alpha, alpha);
}`;

// Filled triangle meshes: one instance per triangle, with optional scalar LUT
// color and antialiased barycentric edge strokes.
export const MESH_VS = `#version 300 es
in float ax0; in float ay0; in float ax1; in float ay1; in float ax2; in float ay2; in float a_cval;
in vec4 a_rgba; in vec4 a_style; in vec4 a_stroke;
uniform vec2 u_xmap; uniform vec2 u_ymap;
uniform vec2 u_x0meta; uniform vec2 u_x1meta; uniform vec2 u_x2meta;
uniform vec2 u_y0meta; uniform vec2 u_y1meta; uniform vec2 u_y2meta;
uniform int u_x0mode; uniform int u_x1mode; uniform int u_x2mode;
uniform int u_y0mode; uniform int u_y1mode; uniform int u_y2mode;
uniform int u_colorMode;
out float v_cval; out vec3 v_bary; out vec4 v_rgba; out vec4 v_style; out vec4 v_stroke;
${AXIS_GLSL}
void main() {
  int vertex = gl_VertexID % 3;
  float x = vertex == 0 ? ax0 : (vertex == 1 ? ax1 : ax2);
  float y = vertex == 0 ? ay0 : (vertex == 1 ? ay1 : ay2);
  vec2 xm = vertex == 0 ? u_x0meta : (vertex == 1 ? u_x1meta : u_x2meta);
  vec2 ym = vertex == 0 ? u_y0meta : (vertex == 1 ? u_y1meta : u_y2meta);
  int xmode = vertex == 0 ? u_x0mode : (vertex == 1 ? u_x1mode : u_x2mode);
  int ymode = vertex == 0 ? u_y0mode : (vertex == 1 ? u_y1mode : u_y2mode);
  gl_Position = vec4(xyMap(x, u_xmap, xm, xmode), xyMap(y, u_ymap, ym, ymode), 0.0, 1.0);
  v_cval = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
  v_bary = vertex == 0 ? vec3(1.,0.,0.) : (vertex == 1 ? vec3(0.,1.,0.) : vec3(0.,0.,1.));
  v_rgba = a_rgba; v_style = a_style; v_stroke = a_stroke;
}`;

export const MESH_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_color; uniform int u_colorMode; uniform sampler2D u_lut; uniform float u_opacity;
uniform vec4 u_stroke; uniform float u_strokeWidth; uniform int u_strokeMode; uniform float u_strokeOpacity;
in float v_cval; in vec3 v_bary; in vec4 v_rgba; in vec4 v_style; in vec4 v_stroke;
out vec4 outColor;
void main() {
  vec4 paint = u_colorMode == 3 ? v_rgba : (u_colorMode == 0 ? u_color : vec4(texture(u_lut, vec2(clamp(v_cval, 0.0, 1.0), 0.5)).rgb, 1.0));
  float alpha = (v_style.y >= 0.0 ? v_style.y : paint.a) * v_style.x * u_opacity;
  vec4 fill = vec4(paint.rgb * alpha, alpha);
  float strokeWidth = v_style.z >= 0.0 ? v_style.z : u_strokeWidth;
  if (strokeWidth > 0.0) {
    float edge = min(v_bary.x, min(v_bary.y, v_bary.z));
    float coverage = smoothstep(0.0, max(fwidth(edge) * strokeWidth, 1e-5), edge);
    // Both stroke sources ship straight alpha; the per-item alpha stack
    // applies to scalar strokes as well (parity with static exporters).
    vec4 strokeSrc = u_strokeMode == 1 ? v_stroke : (u_strokeMode == 2 ? paint : u_stroke);
    float strokeAlpha = (v_style.y >= 0.0 ? v_style.y : strokeSrc.a) * v_style.x * u_strokeOpacity;
    vec4 stroke = vec4(strokeSrc.rgb * strokeAlpha, strokeAlpha);
    outColor = mix(stroke, fill, coverage);
  } else {
    outColor = fill;
  }
}`;

// Mark-fill gradients (spec/api/styling.md#styling-the-marks): up to 8 stops,
// interpolated in premultiplied alpha so a fade to `transparent` keeps the hue
// (no dark fringe). u_gradMode: 0=off, 1=mark space (t runs along the mark's
// value axis, 0 at the base, 1 at the tip/line), 2=plot space (screen axes —
// the canvas IS the plot box). Direction follows CSS: the first stop sits at
// the gradient-line start, so "to bottom" (the default) starts at the tip.
const GRAD_GLSL = `
uniform int u_gradMode; uniform int u_gradDir; uniform int u_gradCount;
uniform float u_gradPos[8]; uniform vec4 u_gradColor[8];
vec4 xyGradSample(float t) {
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
float xyGradT(float markT, vec2 res) {
  float t;
  if (u_gradMode == 2) {
    vec2 f = gl_FragCoord.xy / max(res, vec2(1.0));
    t = u_gradDir == 0 ? 1.0 - f.y : u_gradDir == 1 ? f.y : u_gradDir == 2 ? 1.0 - f.x : f.x;
  } else {
    t = u_gradDir == 0 ? 1.0 - markT : markT;
  }
  return clamp(t, 0.0, 1.0);
}`;

// Area: one instanced strip per segment, filling between the top line (y) and a
// baseline column. Baseline is offset-encoded independently from y.
export const AREA_VS = `#version 300 es
in float ax0; in float ax1; in float ay0; in float ay1; in float ab0; in float ab1;
uniform vec2 u_xmap; uniform vec2 u_ymap; uniform vec2 u_bmap;
uniform vec2 u_xmeta; uniform vec2 u_ymeta; uniform vec2 u_bmeta;
uniform int u_xmode; uniform int u_ymode;
uniform float u_revealProgress; uniform float u_revealSegments;
out float v_top; out float v_base; out float v_pos;
const vec2 corners[4] = vec2[4](vec2(0.,0.), vec2(1.,0.), vec2(0.,1.), vec2(1.,1.));
${AXIS_GLSL}
void main() {
  vec2 c = corners[gl_VertexID];
  float x0 = xyMap(ax0, u_xmap, u_xmeta, u_xmode);
  float x1 = xyMap(ax1, u_xmap, u_xmeta, u_xmode);
  float y0 = xyMap(ay0, u_ymap, u_ymeta, u_ymode);
  float y1 = xyMap(ay1, u_ymap, u_ymeta, u_ymode);
  float b0 = xyMap(ab0, u_bmap, u_bmeta, u_ymode);
  float b1 = xyMap(ab1, u_bmap, u_bmeta, u_ymode);
  float reveal = clamp(u_revealProgress * u_revealSegments - float(gl_InstanceID), 0.0, 1.0);
  x1 = mix(x0, x1, reveal);
  y1 = mix(y0, y1, reveal);
  b1 = mix(b0, b1, reveal);
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

export const AREA_FS = `#version 300 es
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
    premult = xyGradSample(xyGradT(markT, u_res)) * u_color.a;
  }
  if (premult.a <= 0.001) discard;
  outColor = premult;
}`;

// Rectangles: one instanced quad per mark. Geometry columns are left/right and
// bottom/top in data space, each offset-encoded independently (§4). This is the
// primitive for histogram, bar/column, waterfall, and later heatmap cells.
export const RECT_VS = `#version 300 es
in float ax0; in float ax1; in float ay0; in float ay1;
uniform vec2 u_x0map; uniform vec2 u_x1map; uniform vec2 u_y0map; uniform vec2 u_y1map;
uniform vec2 u_x0meta; uniform vec2 u_x1meta; uniform vec2 u_y0meta; uniform vec2 u_y1meta;
uniform int u_xmode; uniform int u_ymode;
uniform vec4 u_edgePad;
uniform vec2 u_res;
in float a_cval; in vec4 a_rgba; in vec4 a_style; in vec4 a_stroke; in vec2 a_radius;
uniform int u_colorMode;
out float v_lutCoord;
out vec2 v_local; out vec2 v_half; out float v_t;
out vec4 v_rgba; out vec4 v_style; out vec4 v_stroke; out vec2 v_radius;
const vec2 corners[4] = vec2[4](vec2(0.,0.), vec2(1.,0.), vec2(0.,1.), vec2(1.,1.));
${AXIS_GLSL}
void main() {
  vec2 c = corners[gl_VertexID];
  float x0 = xyMap(ax0, u_x0map, u_x0meta, u_xmode) + u_edgePad.x;
  float x1 = xyMap(ax1, u_x1map, u_x1meta, u_xmode) + u_edgePad.y;
  float y0 = xyMap(ay0, u_y0map, u_y0meta, u_ymode) + u_edgePad.z;
  float y1 = xyMap(ay1, u_y1map, u_y1meta, u_ymode) + u_edgePad.w;
  v_lutCoord = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
  // Pixel-space local frame for the rounded-corner/stroke SDF (v_half is
  // constant across the quad; v_local interpolates to the fragment offset).
  vec2 pA = (vec2(x0, y0) * 0.5 + 0.5) * u_res;
  vec2 pB = (vec2(x1, y1) * 0.5 + 0.5) * u_res;
  v_half = abs(pB - pA) * 0.5;
  v_local = mix(pA, pB, c) - (pA + pB) * 0.5;
  v_t = c.y;
  v_rgba = a_rgba; v_style = a_style; v_stroke = a_stroke; v_radius = a_radius;
  gl_Position = vec4(mix(x0, x1, c.x), mix(y0, y1, c.y), 0.0, 1.0);
}`;

// Compact bars: one position column, one value column, optional value0 column,
// and scalar width. This keeps common bar payloads to two columns instead of
// four edge columns while preserving the full rectangle primitive for irregular
// histograms/candles/waterfalls.
export const BAR_VS = `#version 300 es
in float a_pos; in float a_v0; in float a_v1; in float a_cval;
in float a_prevx; in float a_prevy; in float a_prevx1;
in vec4 a_rgba; in vec4 a_style; in vec4 a_stroke; in vec2 a_radius;
uniform vec2 u_pmap; uniform vec2 u_v0map; uniform vec2 u_v1map;
uniform vec2 u_pmeta; uniform vec2 u_v0meta; uniform vec2 u_v1meta;
uniform int u_pmode; uniform int u_vmode;
uniform float u_width; uniform int u_orientation; uniform int u_v0Mode; uniform float u_v0Const;
uniform float u_v0EdgePad;
uniform float u_animationProgress;
uniform float u_transitionProgress; uniform int u_transitionActive; uniform float u_prevWidth;
uniform vec2 u_res;
uniform int u_colorMode;
out float v_lutCoord;
out vec2 v_local; out vec2 v_half; out float v_t;
out vec4 v_rgba; out vec4 v_style; out vec4 v_stroke; out vec2 v_radius;
const vec2 corners[4] = vec2[4](vec2(0.,0.), vec2(1.,0.), vec2(0.,1.), vec2(1.,1.));
${AXIS_GLSL}
void main() {
  vec2 c = corners[gl_VertexID];
  float nextP = xyMap(a_pos, u_pmap, u_pmeta, u_pmode);
  float nextV0 = u_v0Mode == 0 ? u_v0Const : xyMap(a_v0, u_v0map, u_v0meta, u_vmode);
  float nextV1 = xyMap(a_v1, u_v1map, u_v1meta, u_vmode);
  float p = nextP;
  float v0 = nextV0;
  float v1 = nextV1;
  float width = u_width;
  if (u_transitionActive == 1) {
    p = mix(xyMap(a_prevx, u_pmap, u_pmeta, u_pmode), nextP, u_transitionProgress);
    // Previous baselines are encoded in the next value column's coordinate
    // system, which lets constant and per-row baselines share one attribute.
    v0 = mix(xyMap(a_prevx1, u_v1map, u_v1meta, u_vmode), nextV0, u_transitionProgress);
    v1 = mix(xyMap(a_prevy, u_v1map, u_v1meta, u_vmode), nextV1, u_transitionProgress);
    width = mix(u_prevWidth, u_width, u_transitionProgress);
  }
  v0 += u_v0EdgePad;
  v1 = mix(v0, v1, u_animationProgress);
  float halfW = abs(width * u_pmap.x) * 0.5;
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
  v_rgba = a_rgba; v_style = a_style; v_stroke = a_stroke; v_radius = a_radius;
}`;

// Shared by the rect and compact-bar programs: flat fill or LUT color, then an
// optional mark gradient, then an optional rounded-corner + stroke SDF pass.
// With radius/stroke/gradient at their defaults this reduces exactly to the
// old flat-quad output (cover = 1, no SDF sampled), so plain bars stay
// pixel-identical.
export const RECT_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_color; uniform int u_colorMode; uniform sampler2D u_lut;
uniform vec2 u_radius; uniform float u_strokeWidth; uniform vec4 u_stroke;
uniform int u_strokeMode; uniform float u_strokeOpacity;
uniform float u_opacity;
uniform vec2 u_res;
in float v_lutCoord;
in vec2 v_local; in vec2 v_half; in float v_t;
in vec4 v_rgba; in vec4 v_style; in vec4 v_stroke; in vec2 v_radius;
out vec4 outColor;
${GRAD_GLSL}
void main() {
  vec4 paint = u_colorMode == 3 ? v_rgba : (u_colorMode == 0 ? u_color : vec4(texture(u_lut, vec2(clamp(v_lutCoord, 0.0, 1.0), 0.5)).rgb, 1.0));
  float alpha = (v_style.y >= 0.0 ? v_style.y : paint.a) * v_style.x * u_opacity;
  vec4 premult = vec4(paint.rgb * alpha, alpha);
  if (u_gradMode != 0) {
    vec4 gradient = xyGradSample(xyGradT(v_t, u_res));
    float gradientAlpha = (v_style.y >= 0.0 ? v_style.y : gradient.a) * v_style.x * u_opacity;
    // Gradient stops are uploaded premultiplied. Recover their straight RGB
    // before applying an artist-alpha override, then premultiply the result.
    vec3 gradientRgb = gradient.a > 1e-6 ? gradient.rgb / gradient.a : vec3(0.0);
    premult = vec4(gradientRgb * gradientAlpha, gradientAlpha);
  }
  vec2 radius = v_radius.x >= 0.0 ? v_radius : u_radius;
  float strokeWidth = v_style.z >= 0.0 ? v_style.z : u_strokeWidth;
  if (radius.x > 0.0 || radius.y > 0.0 || strokeWidth > 0.0) {
    // u_radius = (tip, base) in mark space: v_t > 0.5 is the tip half, so
    // corner_radius=(6, 0) rounds only the value end of the bar. On the
    // straight sides the SDF reduces to |local|-half independent of r, so
    // differing radii meet with no seam.
    float r = min(v_t > 0.5 ? radius.x : radius.y, min(v_half.x, v_half.y));
    vec2 q = abs(v_local) - (v_half - vec2(r));
    float d = length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - r;
    float aa = 0.75;
    if (strokeWidth > 0.0) {
      // Both stroke sources ship straight alpha; the per-item alpha stack
      // applies to scalar strokes as well (parity with static exporters).
      vec4 strokeSrc = u_strokeMode == 1 ? v_stroke : (u_strokeMode == 2 ? paint : u_stroke);
      float strokeAlpha = (v_style.y >= 0.0 ? v_style.y : strokeSrc.a) * v_style.x * u_strokeOpacity;
      vec4 stroke = vec4(strokeSrc.rgb * strokeAlpha, strokeAlpha);
      float inner = 1.0 - smoothstep(-aa, aa, d + strokeWidth);
      premult = mix(stroke, premult, inner);
    }
    premult *= 1.0 - smoothstep(-aa, aa, d);
  }
  if (premult.a <= 0.001) discard;
  outColor = premult;
}`;

// ---------------------------------------------------------------------------
// curve:"smooth" — monotone cubic (Fritsch–Carlson) resampling for line/area.
// Purely visual: the GPU geometry densifies, while hover/tooltips keep reading
// the source rows (`g._cpu` stays the original columns). The interpolant never
// overshoots the data (its whole point), so it is safe on M4-decimated tiers,
// and per-axis affine maps commute with the construction, so resampling the
// offset-encoded f32 columns (§4) is exact. Output is capped at `maxOut`
// vertices; past that the polyline is sub-pixel dense and smoothing is a no-op.
// ---------------------------------------------------------------------------
function xyMonotoneTangents(x, y, n) {
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

export function xySmoothResample(x, y, extra, n, maxOut) {
  if (n < 3) return null;
  const sub = Math.max(1, Math.min(16, Math.floor(maxOut / n)));
  if (sub <= 1) return null; // already pixel-dense; identity at pixel scale
  for (let i = 0; i < n; i++) {
    if (!Number.isFinite(x[i]) || !Number.isFinite(y[i])) return null;
    if (i > 0 && x[i] < x[i - 1]) return null; // needs sorted x (line ingest sorts)
    if (extra && !Number.isFinite(extra[i])) return null;
  }
  const my = xyMonotoneTangents(x, y, n);
  const me = extra ? xyMonotoneTangents(x, extra, n) : null;
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
