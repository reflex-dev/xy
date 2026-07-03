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
in float ax; in float ay; in float a_cval; in float a_sval; in float a_sel;
uniform vec2 u_xmap; uniform vec2 u_ymap;
uniform float u_size; uniform int u_sizeMode; uniform vec2 u_sizeRange;
uniform int u_colorMode; uniform float u_dpr; uniform int u_selActive;
out float v_lutCoord; out float v_dim;
void main() {
  gl_Position = vec4(ax * u_xmap.x + u_xmap.y, ay * u_ymap.x + u_ymap.y, 0.0, 1.0);
  float sz = u_sizeMode == 1 ? mix(u_sizeRange.x, u_sizeRange.y, a_sval) : u_size;
  gl_PointSize = sz * u_dpr;
  // continuous: coord = value in [0,1]; categorical: center of texel a_cval.
  v_lutCoord = u_colorMode == 2 ? (a_cval + 0.5) / 256.0 : a_cval;
  // Unselected marks dim when a selection is active (§34 selected/unselected styling).
  v_dim = (u_selActive == 1 && a_sel < 0.5) ? 0.12 : 1.0;
}`;

const POINT_FS = `#version 300 es
precision highp float; precision highp int;
uniform vec4 u_color; uniform int u_colorMode; uniform sampler2D u_lut; uniform float u_opacity;
in float v_lutCoord; in float v_dim;
out vec4 outColor;
void main() {
  vec2 d = gl_PointCoord - 0.5;
  float r = length(d) * 2.0;
  float aa = fwidth(r) + 1e-4;
  float cov = 1.0 - smoothstep(1.0 - aa, 1.0, r);
  if (cov <= 0.001) discard;
  vec3 rgb = u_colorMode == 0 ? u_color.rgb : texture(u_lut, vec2(clamp(v_lutCoord, 0.0, 1.0), 0.5)).rgb;
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
