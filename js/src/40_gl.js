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
  const vsh = compile(gl, gl.VERTEX_SHADER, vs);
  const fsh = compile(gl, gl.FRAGMENT_SHADER, fs);
  gl.attachShader(p, vsh);
  gl.attachShader(p, fsh);
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

function uniformOf(gl, prog, name) {
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
out float v_lutCoord; out float v_dim; out float v_dval;
${AXIS_GLSL}
void main() {
  gl_Position = vec4(fcMap(ax, u_xmap, u_xmeta, u_xmode), fcMap(ay, u_ymap, u_ymeta, u_ymode), 0.0, 1.0);
  float sz = u_sizeMode == 1 ? mix(u_sizeRange.x, u_sizeRange.y, a_sval) : u_size;
  gl_PointSize = sz * u_dpr;
  // continuous: coord = value in [0,1]; categorical: center of texel a_cval.
  v_lutCoord = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
  // Local log-density LUT coord (drill handoff, §5): lets freshly drilled
  // points wear the density colormap so the texture->points swap is seamless.
  v_dval = a_dval;
  // Unselected marks dim when a selection is active (§34 selected/unselected styling).
  v_dim = u_selActive == 1 ? mix(u_unselectedOpacity, u_selectedOpacity, step(0.5, a_sel)) : 1.0;
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

// Density (Tier 2): a fullscreen quad; each fragment reconstructs its data-space
// coordinate from the view range, maps into the grid's data range, samples the
// pre-normalized log-density value, and colormaps (§5, §F6). Data outside the
// grid range is transparent — so a stale grid stays correctly positioned during
// pan until the re-bin arrives (§17).
const DENSITY_VS = `#version 300 es
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

// Heatmap grid: a regular value matrix as one R8 texture. Byte 0 means missing
// (transparent); bytes 1..255 map back to normalized values [0,1].
const HEATMAP_VS = `#version 300 es
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

const HEATMAP_FS = `#version 300 es
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
  float raw = texture(u_grid, uv).r;
  if (raw <= 0.0) discard;
  float t = clamp((raw * 255.0 - 1.0) / 254.0, 0.0, 1.0);
  vec3 rgb = texture(u_lut, vec2(t, 0.5)).rgb;
  outColor = vec4(rgb * u_opacity, u_opacity);
}`;

const LINE_VS = `#version 300 es
in float ax0; in float ay0; in float ax1; in float ay1;
uniform vec2 u_xmap; uniform vec2 u_ymap; uniform vec2 u_res; uniform float u_width;
uniform vec2 u_xmeta; uniform vec2 u_ymeta; uniform int u_xmode; uniform int u_ymode;
out float v_off;
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

// Area: one instanced strip per segment, filling between the top line (y) and a
// baseline column. Baseline is offset-encoded independently from y.
const AREA_VS = `#version 300 es
in float ax0; in float ax1; in float ay0; in float ay1; in float ab0; in float ab1;
uniform vec2 u_xmap; uniform vec2 u_ymap; uniform vec2 u_bmap;
uniform vec2 u_xmeta; uniform vec2 u_ymeta; uniform vec2 u_bmeta;
uniform int u_xmode; uniform int u_ymode;
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
  gl_Position = vec4(mix(x0, x1, c.x), mix(base, top, c.y), 0.0, 1.0);
}`;

const AREA_FS = `#version 300 es
precision highp float;
uniform vec4 u_color;
out vec4 outColor;
void main() {
  if (u_color.a <= 0.001) discard;
  outColor = vec4(u_color.rgb * u_color.a, u_color.a);
}`;

// Rectangles: one instanced quad per mark. Geometry columns are left/right and
// bottom/top in data space, each offset-encoded independently (§4). This is the
// primitive for histogram, bar/column, waterfall, and later heatmap cells.
const RECT_VS = `#version 300 es
in float ax0; in float ax1; in float ay0; in float ay1;
uniform vec2 u_x0map; uniform vec2 u_x1map; uniform vec2 u_y0map; uniform vec2 u_y1map;
uniform vec2 u_x0meta; uniform vec2 u_x1meta; uniform vec2 u_y0meta; uniform vec2 u_y1meta;
uniform int u_xmode; uniform int u_ymode;
uniform vec4 u_edgePad;
in float a_cval; uniform int u_colorMode;
out float v_lutCoord;
const vec2 corners[4] = vec2[4](vec2(0.,0.), vec2(1.,0.), vec2(0.,1.), vec2(1.,1.));
${AXIS_GLSL}
void main() {
  vec2 c = corners[gl_VertexID];
  float x0 = fcMap(ax0, u_x0map, u_x0meta, u_xmode) + u_edgePad.x;
  float x1 = fcMap(ax1, u_x1map, u_x1meta, u_xmode) + u_edgePad.y;
  float y0 = fcMap(ay0, u_y0map, u_y0meta, u_ymode) + u_edgePad.z;
  float y1 = fcMap(ay1, u_y1map, u_y1meta, u_ymode) + u_edgePad.w;
  v_lutCoord = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
  gl_Position = vec4(mix(x0, x1, c.x), mix(y0, y1, c.y), 0.0, 1.0);
}`;

// Compact bars: one position column, one value column, optional value0 column,
// and scalar width. This keeps common bar payloads to two columns instead of
// four edge columns while preserving the full rectangle primitive for irregular
// histograms/candles/waterfalls.
const BAR_VS = `#version 300 es
in float a_pos; in float a_v0; in float a_v1; in float a_cval;
uniform vec2 u_pmap; uniform vec2 u_v0map; uniform vec2 u_v1map;
uniform vec2 u_pmeta; uniform vec2 u_v0meta; uniform vec2 u_v1meta;
uniform int u_pmode; uniform int u_vmode;
uniform float u_width; uniform int u_orientation; uniform int u_v0Mode; uniform float u_v0Const;
uniform float u_v0EdgePad;
uniform int u_colorMode;
out float v_lutCoord;
const vec2 corners[4] = vec2[4](vec2(0.,0.), vec2(1.,0.), vec2(0.,1.), vec2(1.,1.));
${AXIS_GLSL}
void main() {
  vec2 c = corners[gl_VertexID];
  float p = fcMap(a_pos, u_pmap, u_pmeta, u_pmode);
  float halfW = abs(u_width * u_pmap.x) * 0.5;
  float v0 = (u_v0Mode == 0 ? u_v0Const : fcMap(a_v0, u_v0map, u_v0meta, u_vmode)) + u_v0EdgePad;
  float v1 = fcMap(a_v1, u_v1map, u_v1meta, u_vmode);
  v_lutCoord = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
  if (u_orientation == 0) {
    gl_Position = vec4(mix(p - halfW, p + halfW, c.x), mix(v0, v1, c.y), 0.0, 1.0);
  } else {
    gl_Position = vec4(mix(v0, v1, c.x), mix(p - halfW, p + halfW, c.y), 0.0, 1.0);
  }
}`;

const RECT_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_color; uniform int u_colorMode; uniform sampler2D u_lut;
in float v_lutCoord;
out vec4 outColor;
void main() {
  if (u_color.a <= 0.001) discard;
  vec3 rgb = u_colorMode == 0 ? u_color.rgb : texture(u_lut, vec2(clamp(v_lutCoord, 0.0, 1.0), 0.5)).rgb;
  outColor = vec4(rgb * u_color.a, u_color.a);
}`;
