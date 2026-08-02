const POINT_COUNT = 1024;
const CANARY_SIZE = 7;
const MAX_DPR = 2;
const SAMPLE_LIMIT = 6000;

const PALETTE = [
  [0.72, 0.95, 0.29],
  [0.39, 0.91, 0.74],
  [0.39, 0.66, 1.0],
  [1.0, 0.71, 0.37],
  [0.94, 0.46, 0.71],
];

const LINE_VS = `#version 300 es
precision highp float;
layout(location = 0) in float a_x;
layout(location = 1) in float a_y;
uniform float u_yScale;
out float v_x;
void main() {
  v_x = a_x;
  gl_Position = vec4(a_x * 2.0 - 1.0, a_y * u_yScale, 0.0, 1.0);
}`;

const LINE_FS = `#version 300 es
precision highp float;
in float v_x;
uniform vec3 u_color;
out vec4 outColor;
void main() {
  vec3 tone = mix(u_color * 0.68, u_color, smoothstep(0.0, 1.0, v_x));
  float alpha = 0.96;
  outColor = vec4(tone * alpha, alpha);
}`;

const PICK_VS = `#version 300 es
precision highp float;
precision highp int;
layout(location = 0) in float a_x;
layout(location = 1) in float a_y;
uniform float u_yScale;
uniform float u_pointSize;
flat out uint v_id;
void main() {
  gl_Position = vec4(a_x * 2.0 - 1.0, a_y * u_yScale, 0.0, 1.0);
  gl_PointSize = u_pointSize;
  v_id = uint(gl_VertexID) + 1u;
}`;

const PICK_FS = `#version 300 es
precision highp float;
precision highp int;
flat in uint v_id;
out vec4 outColor;
void main() {
  vec2 point = gl_PointCoord - vec2(0.5);
  if (dot(point, point) > 0.25) discard;
  uint r = v_id & 255u;
  uint g = (v_id >> 8u) & 255u;
  uint b = (v_id >> 16u) & 255u;
  outColor = vec4(float(r), float(g), float(b), 255.0) / 255.0;
}`;

const $ = (selector) => document.querySelector(selector);
const nextFrame = () => new Promise((resolve) => requestAnimationFrame(resolve));
const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

function createSampleBuffer() {
  return {
    values: new Float64Array(SAMPLE_LIMIT),
    length: 0,
    head: 0,
  };
}

function percentile(samples, fraction) {
  if (!samples.length) return 0;
  const sorted = Array.from(samples.values.subarray(0, samples.length)).sort(
    (a, b) => a - b,
  );
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * fraction) - 1);
  return sorted[Math.max(0, index)];
}

function pushSample(samples, value) {
  if (samples.length < SAMPLE_LIMIT) {
    samples.values[samples.length] = value;
    samples.length += 1;
    return;
  }
  samples.values[samples.head] = value;
  samples.head = (samples.head + 1) % SAMPLE_LIMIT;
}

function clearSamples(samples) {
  samples.length = 0;
  samples.head = 0;
}

function formatMs(value) {
  return Number.isFinite(value) && value > 0 ? `${value.toFixed(2)} ms` : "—";
}

function readGlIdentity(gl) {
  const debugInfo = gl.getExtension("WEBGL_debug_renderer_info");
  return {
    vendor: debugInfo
      ? gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL)
      : gl.getParameter(gl.VENDOR),
    renderer: debugInfo
      ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL)
      : gl.getParameter(gl.RENDERER),
    version: gl.getParameter(gl.VERSION),
    shadingLanguageVersion: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
  };
}

function compileShader(gl, type, source) {
  const shader = gl.createShader(type);
  if (!shader) throw new Error("WebGL could not allocate a shader");
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(shader) || "unknown shader error";
    gl.deleteShader(shader);
    throw new Error(message);
  }
  return shader;
}

function createProgram(gl, vertexSource, fragmentSource) {
  let vertex = null;
  let fragment = null;
  let program = null;
  try {
    vertex = compileShader(gl, gl.VERTEX_SHADER, vertexSource);
    fragment = compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource);
    program = gl.createProgram();
    if (!program) throw new Error("WebGL could not allocate a program");
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(program) || "unknown link error");
    }
    const linked = program;
    program = null;
    return linked;
  } finally {
    if (vertex) gl.deleteShader(vertex);
    if (fragment) gl.deleteShader(fragment);
    if (program) gl.deleteProgram(program);
  }
}

function createProgramSet(gl) {
  let line = null;
  let pick = null;
  let poisonVao = null;
  let poisonTransformFeedback = null;
  let poisonUniformBuffer = null;
  try {
    line = createProgram(gl, LINE_VS, LINE_FS);
    pick = createProgram(gl, PICK_VS, PICK_FS);
    poisonVao = gl.createVertexArray();
    poisonTransformFeedback = gl.createTransformFeedback();
    poisonUniformBuffer = gl.createBuffer();
    if (!poisonVao || !poisonTransformFeedback || !poisonUniformBuffer) {
      throw new Error("WebGL could not allocate state-stress resources");
    }
    gl.bindBuffer(gl.UNIFORM_BUFFER, poisonUniformBuffer);
    gl.bufferData(gl.UNIFORM_BUFFER, 16, gl.STATIC_DRAW);
    gl.bindBuffer(gl.UNIFORM_BUFFER, null);
    return {
      line,
      pick,
      poisonVao,
      poisonTransformFeedback,
      poisonUniformBuffer,
      lineUniforms: {
        yScale: gl.getUniformLocation(line, "u_yScale"),
        color: gl.getUniformLocation(line, "u_color"),
      },
      pickUniforms: {
        yScale: gl.getUniformLocation(pick, "u_yScale"),
        pointSize: gl.getUniformLocation(pick, "u_pointSize"),
      },
    };
  } catch (error) {
    if (line) gl.deleteProgram(line);
    if (pick) gl.deleteProgram(pick);
    if (poisonVao) gl.deleteVertexArray(poisonVao);
    if (poisonTransformFeedback) gl.deleteTransformFeedback(poisonTransformFeedback);
    if (poisonUniformBuffer) gl.deleteBuffer(poisonUniformBuffer);
    throw error;
  }
}

function destroyProgramSet(gl, programs) {
  if (!programs || gl.isContextLost()) return;
  gl.deleteProgram(programs.line);
  gl.deleteProgram(programs.pick);
  gl.deleteVertexArray(programs.poisonVao);
  gl.deleteTransformFeedback(programs.poisonTransformFeedback);
  gl.deleteBuffer(programs.poisonUniformBuffer);
}

function beginPass(gl, framebuffer, width, height, blend) {
  gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
  const colorTarget = framebuffer ? gl.COLOR_ATTACHMENT0 : gl.BACK;
  gl.readBuffer(colorTarget);
  gl.drawBuffers([colorTarget]);
  gl.viewport(0, 0, width, height);
  gl.enable(gl.SCISSOR_TEST);
  gl.scissor(0, 0, width, height);
  gl.disable(gl.DEPTH_TEST);
  gl.disable(gl.CULL_FACE);
  gl.disable(gl.STENCIL_TEST);
  gl.disable(gl.POLYGON_OFFSET_FILL);
  gl.disable(gl.RASTERIZER_DISCARD);
  gl.disable(gl.SAMPLE_ALPHA_TO_COVERAGE);
  gl.disable(gl.SAMPLE_COVERAGE);
  gl.disable(gl.DITHER);
  gl.frontFace(gl.CCW);
  gl.cullFace(gl.BACK);
  gl.depthFunc(gl.LESS);
  gl.colorMask(true, true, true, true);
  gl.depthMask(true);
  gl.stencilMask(0xffffffff);
  gl.stencilFunc(gl.ALWAYS, 0, 0xffffffff);
  gl.stencilOp(gl.KEEP, gl.KEEP, gl.KEEP);
  gl.polygonOffset(0, 0);
  gl.blendColor(0, 0, 0, 0);
  gl.blendEquation(gl.FUNC_ADD);
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  if (blend) gl.enable(gl.BLEND);
  else gl.disable(gl.BLEND);
  // This experiment only touches units 0–3. Reset every touched unit so a
  // previous virtual client cannot leak texture/sampler state into the next.
  for (let unit = 0; unit < 4; unit += 1) {
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, null);
    gl.bindSampler(unit, null);
  }
  gl.activeTexture(gl.TEXTURE0);
  gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, null);
  gl.bindVertexArray(null);
  gl.bindBuffer(gl.ARRAY_BUFFER, null);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, null);
  for (let binding = 0; binding < 4; binding += 1) {
    gl.bindBufferBase(gl.UNIFORM_BUFFER, binding, null);
  }
  gl.bindBuffer(gl.UNIFORM_BUFFER, null);
  gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
  gl.bindBuffer(gl.PIXEL_UNPACK_BUFFER, null);
  gl.pixelStorei(gl.PACK_ALIGNMENT, 4);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
  gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.BROWSER_DEFAULT_WEBGL);
  gl.useProgram(null);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT);
}

function poisonState(gl, programs, width, height) {
  gl.disable(gl.BLEND);
  gl.enable(gl.DEPTH_TEST);
  gl.enable(gl.CULL_FACE);
  gl.enable(gl.STENCIL_TEST);
  gl.enable(gl.POLYGON_OFFSET_FILL);
  gl.colorMask(false, false, false, false);
  gl.frontFace(gl.CW);
  gl.cullFace(gl.FRONT);
  gl.depthFunc(gl.GREATER);
  gl.stencilMask(0);
  gl.stencilFunc(gl.NEVER, 1, 0);
  gl.stencilOp(gl.REPLACE, gl.REPLACE, gl.REPLACE);
  gl.polygonOffset(1, 1);
  gl.blendColor(1, 0, 1, 0.5);
  gl.blendEquation(gl.FUNC_REVERSE_SUBTRACT);
  gl.blendFunc(gl.ZERO, gl.ZERO);
  gl.viewport(1, 2, Math.max(1, width - 3), Math.max(1, height - 4));
  gl.scissor(Math.max(0, width - 2), Math.max(0, height - 2), 1, 1);
  gl.readBuffer(gl.NONE);
  gl.drawBuffers([gl.NONE]);
  gl.pixelStorei(gl.PACK_ALIGNMENT, 1);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
  gl.activeTexture(gl.TEXTURE3);
  gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, programs.poisonTransformFeedback);
  for (let binding = 0; binding < 4; binding += 1) {
    gl.bindBufferBase(gl.UNIFORM_BUFFER, binding, programs.poisonUniformBuffer);
  }
  gl.bindBuffer(gl.UNIFORM_BUFFER, programs.poisonUniformBuffer);
  gl.bindVertexArray(programs.poisonVao);
  gl.useProgram(programs.pick);
}

function drawCanaries(gl, chart, width, height) {
  const size = Math.min(CANARY_SIZE, width, height);
  const idByte = (chart.index + 1) & 255;
  const frameByte = chart.frameByte & 255;
  gl.enable(gl.SCISSOR_TEST);
  gl.colorMask(true, true, true, true);
  gl.disable(gl.BLEND);

  // Top-left in visual canvas coordinates.
  gl.scissor(0, height - size, size, size);
  gl.clearColor(idByte / 255, frameByte / 255, 17 / 255, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);

  // Bottom-right in visual canvas coordinates.
  gl.scissor(width - size, 0, size, size);
  gl.clearColor(idByte / 255, frameByte / 255, 239 / 255, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.scissor(0, 0, width, height);
}

function createChartGpu(gl, chart) {
  const buffer = gl.createBuffer();
  const vao = gl.createVertexArray();
  if (!buffer || !vao) {
    if (buffer) gl.deleteBuffer(buffer);
    if (vao) gl.deleteVertexArray(vao);
    throw new Error("WebGL could not allocate chart geometry");
  }
  gl.bindVertexArray(vao);
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, chart.vertices, gl.DYNAMIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 1, gl.FLOAT, false, 8, 0);
  gl.enableVertexAttribArray(1);
  gl.vertexAttribPointer(1, 1, gl.FLOAT, false, 8, 4);
  gl.bindVertexArray(null);
  chart.gpu = { buffer, vao };
}

function destroyChartGpu(gl, chart) {
  if (!chart.gpu || gl.isContextLost()) {
    chart.gpu = null;
    return;
  }
  gl.deleteBuffer(chart.gpu.buffer);
  gl.deleteVertexArray(chart.gpu.vao);
  chart.gpu = null;
}

function destroyPickTarget(gl, chart) {
  if (!chart.pickTarget || gl.isContextLost()) {
    chart.pickTarget = null;
    return;
  }
  gl.deleteFramebuffer(chart.pickTarget.framebuffer);
  gl.deleteTexture(chart.pickTarget.texture);
  chart.pickTarget = null;
}

function ensurePickTarget(gl, chart, generation) {
  const existing = chart.pickTarget;
  if (
    existing &&
    existing.width === chart.pixelWidth &&
    existing.height === chart.pixelHeight &&
    existing.generation === generation
  ) {
    return existing;
  }
  destroyPickTarget(gl, chart);
  const texture = gl.createTexture();
  const framebuffer = gl.createFramebuffer();
  if (!texture || !framebuffer) {
    if (texture) gl.deleteTexture(texture);
    if (framebuffer) gl.deleteFramebuffer(framebuffer);
    throw new Error("WebGL could not allocate a pick target");
  }
  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texImage2D(
    gl.TEXTURE_2D,
    0,
    gl.RGBA8,
    chart.pixelWidth,
    chart.pixelHeight,
    0,
    gl.RGBA,
    gl.UNSIGNED_BYTE,
    null,
  );
  gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
  gl.framebufferTexture2D(
    gl.FRAMEBUFFER,
    gl.COLOR_ATTACHMENT0,
    gl.TEXTURE_2D,
    texture,
    0,
  );
  const status = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  if (status !== gl.FRAMEBUFFER_COMPLETE) {
    gl.deleteFramebuffer(framebuffer);
    gl.deleteTexture(texture);
    throw new Error(`Incomplete pick framebuffer: 0x${status.toString(16)}`);
  }
  chart.pickTarget = {
    texture,
    framebuffer,
    width: chart.pixelWidth,
    height: chart.pixelHeight,
    generation,
  };
  return chart.pickTarget;
}

function uploadAndDraw(gl, programs, chart) {
  const uploadStart = performance.now();
  gl.bindBuffer(gl.ARRAY_BUFFER, chart.gpu.buffer);
  gl.bufferSubData(gl.ARRAY_BUFFER, 0, chart.vertices);
  const uploadMs = performance.now() - uploadStart;

  const drawStart = performance.now();
  gl.useProgram(programs.line);
  gl.uniform1f(programs.lineUniforms.yScale, chart.yScale);
  gl.uniform3fv(programs.lineUniforms.color, chart.color);
  gl.bindVertexArray(chart.gpu.vao);
  gl.drawArrays(gl.LINE_STRIP, 0, POINT_COUNT);
  drawCanaries(gl, chart, chart.pixelWidth, chart.pixelHeight);
  const drawMs = performance.now() - drawStart;
  return { uploadMs, drawMs };
}

function pickAtPixel(
  gl,
  programs,
  chart,
  generation,
  x,
  y,
  firstVertex = 0,
  vertexCount = POINT_COUNT,
) {
  const target = ensurePickTarget(gl, chart, generation);
  beginPass(gl, target.framebuffer, chart.pixelWidth, chart.pixelHeight, false);
  gl.useProgram(programs.pick);
  gl.uniform1f(programs.pickUniforms.yScale, chart.yScale);
  gl.uniform1f(programs.pickUniforms.pointSize, Math.max(10, 12 * chart.dpr));
  gl.bindVertexArray(chart.gpu.vao);
  gl.drawArrays(gl.POINTS, firstVertex, vertexCount);
  gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
  const pixel = new Uint8Array(4);
  gl.readPixels(
    clamp(Math.floor(x), 0, chart.pixelWidth - 1),
    clamp(Math.floor(y), 0, chart.pixelHeight - 1),
    1,
    1,
    gl.RGBA,
    gl.UNSIGNED_BYTE,
    pixel,
  );
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  const encoded = pixel[0] | (pixel[1] << 8) | (pixel[2] << 16);
  return encoded ? encoded - 1 : -1;
}

function sampleMatches(actual, expected, tolerance = 3) {
  // Channel 1 carries the per-render frame counter and must reject stale frames.
  return actual.every((value, index) => {
    const allowed = index === 1 ? 0 : tolerance;
    return Math.abs(value - expected[index]) <= allowed;
  });
}

class ChartView {
  constructor(index, app) {
    this.index = index;
    this.app = app;
    this.phase = index * 0.47;
    this.amplitude = 0.72 + (index % 7) * 0.035;
    this.yScale = 0.84 + (index % 5) * 0.025;
    this.color = new Float32Array(PALETTE[index % PALETTE.length]);
    this.vertices = new Float32Array(POINT_COUNT * 2);
    this.frameByte = 0;
    this.pixelWidth = 1;
    this.pixelHeight = 1;
    this.dpr = 1;
    this.gpu = null;
    this.pickTarget = null;
    this.target2d = null;
    this.native = null;
    this._pickRaf = 0;
    this._pendingPointer = null;

    this.card = document.createElement("article");
    this.card.className = "chart-card";
    this.card.dataset.state = "building";
    this.card.innerHTML = `
      <div class="chart-card__head">
        <strong>Signal ${String(index + 1).padStart(2, "0")}</strong>
        <span class="chart-state"><span>building</span></span>
      </div>
      <div class="plot-shell">
        <canvas aria-label="Live chart ${index + 1}"></canvas>
        <span class="pick-tooltip"></span>
      </div>
      <div class="chart-card__foot">
        <span>φ ${this.phase.toFixed(2)}</span>
        <span>${POINT_COUNT.toLocaleString()} pts</span>
      </div>`;
    this.canvas = this.card.querySelector("canvas");
    this.tooltip = this.card.querySelector(".pick-tooltip");
    this.stateLabel = this.card.querySelector(".chart-state span");

    this.canvas.addEventListener("pointermove", (event) => this.queuePick(event));
    this.canvas.addEventListener("pointerleave", () => {
      this.tooltip.dataset.show = "false";
      this._pendingPointer = null;
    });
  }

  setState(state, label = state) {
    this.card.dataset.state = state;
    this.stateLabel.textContent = label;
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.dpr = Math.min(MAX_DPR, window.devicePixelRatio || 1);
    const width = Math.max(32, Math.round(rect.width * this.dpr));
    const height = Math.max(24, Math.round(rect.height * this.dpr));
    if (width === this.pixelWidth && height === this.pixelHeight) return false;
    this.pixelWidth = width;
    this.pixelHeight = height;
    this.canvas.width = width;
    this.canvas.height = height;
    return true;
  }

  updateVertices(time) {
    const phase = this.phase;
    const amplitude = this.amplitude;
    for (let index = 0; index < POINT_COUNT; index += 1) {
      const x = index / (POINT_COUNT - 1);
      const primary = Math.sin(x * 12.56637 + time * 1.72 + phase) * 0.47;
      const detail = Math.sin(x * 31.4159 - time * 0.86 + phase * 0.71) * 0.12;
      const drift = (x - 0.5) * 0.11;
      this.vertices[index * 2] = x;
      this.vertices[index * 2 + 1] = (primary + detail + drift) * amplitude;
    }
  }

  queuePick(event) {
    this._pendingPointer = { clientX: event.clientX, clientY: event.clientY };
    if (this._pickRaf) return;
    this._pickRaf = requestAnimationFrame(() => {
      this._pickRaf = 0;
      if (!this._pendingPointer) return;
      this.app.pick(this, this._pendingPointer.clientX, this._pendingPointer.clientY);
    });
  }

  showPick(index, clientX, clientY) {
    if (index < 0 || index >= POINT_COUNT) {
      this.tooltip.dataset.show = "false";
      return;
    }
    const rect = this.canvas.getBoundingClientRect();
    const localX = clamp(clientX - rect.left, 0, rect.width);
    const localY = clamp(clientY - rect.top, 0, rect.height);
    const y = this.vertices[index * 2 + 1] * this.yScale;
    this.tooltip.textContent = `#${index}  y ${y.toFixed(3)}`;
    this.tooltip.dataset.show = "true";
    const gap = 7;
    const tooltipWidth = this.tooltip.offsetWidth;
    const tooltipHeight = this.tooltip.offsetHeight;
    let left = localX + gap;
    let top = localY - gap - tooltipHeight;
    if (left + tooltipWidth > rect.width) left = localX - gap - tooltipWidth;
    if (top < 0) top = localY + gap;
    this.tooltip.style.left = `${clamp(left, 0, rect.width - tooltipWidth)}px`;
    this.tooltip.style.top = `${clamp(top, 0, rect.height - tooltipHeight)}px`;
  }
}

class SharedBackend {
  constructor(app) {
    this.app = app;
    this.mode = "shared";
    this.canvas = document.createElement("canvas");
    this.canvas.width = 1;
    this.canvas.height = 1;
    this.gl = this.canvas.getContext("webgl2", {
      alpha: true,
      antialias: false,
      premultipliedAlpha: true,
      preserveDrawingBuffer: false,
    });
    if (!this.gl) throw new Error("WebGL2 is unavailable");
    this.capacityWidth = 1;
    this.capacityHeight = 1;
    this.generation = 1;
    this.lost = false;
    this.ready = true;
    this.disposed = false;
    this.charts = [];
    this.lossExtension = this.gl.getExtension("WEBGL_lose_context");
    try {
      this.programs = createProgramSet(this.gl);
    } catch (error) {
      // The constructor has not returned, so ExperimentApp cannot dispose this
      // otherwise-detached context from its initialization catch path.
      this.lossExtension?.loseContext();
      throw error;
    }
    this._cycleResolve = null;
    this._cycleTimer = 0;
    this._restoreTimer = 0;

    this._handleContextLost = (event) => {
      event.preventDefault();
      if (this.disposed) return;
      this.lost = true;
      this.ready = false;
      this.programs = null;
      this.generation += 1;
      for (const chart of this.charts) {
        chart.gpu = null;
        chart.pickTarget = null;
        chart.setState("lost", "host lost");
      }
      this.app.onContextLost("Shared host context lost; all clients paused together.");
    };

    this._handleContextRestored = () => {
      if (this.disposed) return;
      let fullyRebuilt = false;
      let nextPrograms = null;
      const rebuiltCharts = [];
      try {
        this.lost = this.gl.isContextLost();
        if (this.lost) throw new Error("WebGL context is still lost after restore event");
        nextPrograms = createProgramSet(this.gl);
        this.programs = nextPrograms;
        this.lossExtension = this.gl.getExtension("WEBGL_lose_context");
        let rebuilt = 0;
        for (const chart of this.charts) {
          createChartGpu(this.gl, chart);
          rebuiltCharts.push(chart);
          chart.pickTarget = null;
          chart.setState("live");
          rebuilt += 1;
        }
        fullyRebuilt = rebuilt === this.charts.length;
        this.ready = fullyRebuilt;
        this.app.needsDraw = fullyRebuilt;
        if (!fullyRebuilt) throw new Error(`Only ${rebuilt}/${this.charts.length} charts rebuilt`);
        this.app.onContextRestored("Shared host restored; all client GPU objects rebuilt.");
      } catch (error) {
        fullyRebuilt = false;
        this.ready = false;
        this.lost = this.gl.isContextLost();
        if (!this.lost) {
          for (const chart of rebuiltCharts) destroyChartGpu(this.gl, chart);
          destroyProgramSet(this.gl, nextPrograms);
        }
        this.programs = null;
        for (const chart of this.charts) {
          chart.gpu = null;
          chart.pickTarget = null;
          chart.setState("error", "restore failed");
        }
        this.app.log(`Shared host restore failed: ${error.message}`);
        this.app.setStatus(`Shared host restore failed: ${error.message}`, "fail");
      } finally {
        clearTimeout(this._cycleTimer);
        clearTimeout(this._restoreTimer);
        this._cycleTimer = 0;
        this._restoreTimer = 0;
        if (this._cycleResolve) {
          this._cycleResolve(fullyRebuilt);
          this._cycleResolve = null;
        }
      }
    };

    this.canvas.addEventListener("webglcontextlost", this._handleContextLost);
    this.canvas.addEventListener("webglcontextrestored", this._handleContextRestored);
  }

  attach(chart) {
    chart.target2d = chart.canvas.getContext("2d", { alpha: true });
    if (!chart.target2d) throw new Error("Canvas 2D is unavailable");
    createChartGpu(this.gl, chart);
    chart.setState("live");
    this.charts.push(chart);
  }

  ensureCapacity(width, height) {
    const nextWidth = Math.max(this.capacityWidth, width);
    const nextHeight = Math.max(this.capacityHeight, height);
    if (nextWidth === this.capacityWidth && nextHeight === this.capacityHeight) return;
    this.capacityWidth = nextWidth;
    this.capacityHeight = nextHeight;
    this.canvas.width = nextWidth;
    this.canvas.height = nextHeight;
  }

  prepareVerification(chart) {
    if (this.disposed || !this.ready || this.lost || this.gl.isContextLost()) {
      return { cropOffsetPixels: 0 };
    }
    // Force a non-zero source-Y during presentation. This exercises the
    // grow-only host crop path even when every visible chart has equal CSS size.
    const tallest = this.charts.reduce(
      (height, item) => Math.max(height, item.pixelHeight),
      chart.pixelHeight,
    );
    const widest = this.charts.reduce(
      (width, item) => Math.max(width, item.pixelWidth),
      chart.pixelWidth,
    );
    this.ensureCapacity(widest, tallest + 17);
    return { cropOffsetPixels: this.capacityHeight - tallest };
  }

  onResize(chart) {
    if (chart.pickTarget && this.ready && !this.lost && !this.gl.isContextLost()) {
      destroyPickTarget(this.gl, chart);
    }
    chart.pickTarget = null;
  }

  render(chart, time, stressState) {
    if (
      this.disposed ||
      !this.ready ||
      this.lost ||
      this.gl.isContextLost() ||
      !this.programs ||
      !chart.gpu ||
      chart.card.dataset.state !== "live"
    ) {
      return null;
    }
    this.ensureCapacity(chart.pixelWidth, chart.pixelHeight);
    chart.updateVertices(time);
    chart.frameByte = (chart.frameByte + 1) & 255;

    beginPass(this.gl, null, chart.pixelWidth, chart.pixelHeight, true);
    const timings = uploadAndDraw(this.gl, this.programs, chart);
    if (this.gl.isContextLost()) {
      this.lost = true;
      this.ready = false;
      return null;
    }

    const presentStart = performance.now();
    const ctx = chart.target2d;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "copy";
    ctx.drawImage(
      this.canvas,
      0,
      this.capacityHeight - chart.pixelHeight,
      chart.pixelWidth,
      chart.pixelHeight,
      0,
      0,
      chart.pixelWidth,
      chart.pixelHeight,
    );
    const presentMs = performance.now() - presentStart;

    if (stressState) poisonState(this.gl, this.programs, chart.pixelWidth, chart.pixelHeight);
    return { ...timings, presentMs };
  }

  pick(chart, clientX, clientY) {
    if (this.disposed || !this.ready || this.lost || this.gl.isContextLost() || !chart.gpu) {
      return -1;
    }
    const rect = chart.canvas.getBoundingClientRect();
    const x = ((clientX - rect.left) * chart.pixelWidth) / Math.max(1, rect.width);
    const topRow = Math.floor(
      ((clientY - rect.top) * chart.pixelHeight) / Math.max(1, rect.height),
    );
    const y = chart.pixelHeight - 1 - topRow;
    return pickAtPixel(this.gl, this.programs, chart, this.generation, x, y);
  }

  pickKnownIndex(chart, index) {
    if (this.disposed || !this.ready || this.lost || this.gl.isContextLost() || !chart.gpu) {
      return -1;
    }
    const x = chart.vertices[index * 2] * (chart.pixelWidth - 1);
    const yValue = chart.vertices[index * 2 + 1] * chart.yScale;
    const y = (yValue * 0.5 + 0.5) * (chart.pixelHeight - 1);
    // The hover pass deliberately gives every sample a generous hit radius.
    // Adjacent points overlap at dense sizes, so render only the requested
    // sample when asserting an exact encoded ID.
    return pickAtPixel(this.gl, this.programs, chart, this.generation, x, y, index, 1);
  }

  inspectCanary(chart) {
    if (this.disposed || !this.ready || this.lost || this.gl.isContextLost()) {
      return { pass: false, lost: true };
    }
    const topLeft = [...chart.target2d.getImageData(2, 2, 1, 1).data];
    const bottomRight = [
      ...chart.target2d.getImageData(
        chart.pixelWidth - 3,
        chart.pixelHeight - 3,
        1,
        1,
      ).data,
    ];
    const id = (chart.index + 1) & 255;
    return {
      pass:
        sampleMatches(topLeft, [id, chart.frameByte, 17, 255]) &&
        sampleMatches(bottomRight, [id, chart.frameByte, 239, 255]),
      topLeft,
      bottomRight,
    };
  }

  getStats() {
    const available =
      !this.disposed && this.ready && !this.lost && !this.gl.isContextLost();
    const live = available ? this.charts.filter((chart) => chart.gpu).length : 0;
    return {
      requestedContexts: 1,
      liveContexts: available ? 1 : 0,
      liveCharts: live,
      requestedCharts: this.charts.length,
      resourceLabel: `1 set / ${live} VBOs`,
    };
  }

  getEnvironment() {
    return readGlIdentity(this.gl);
  }

  async cycleContext() {
    if (!this.lossExtension || this.disposed || this.lost || this.gl.isContextLost()) return false;
    const extension = this.lossExtension;
    const restored = new Promise((resolve) => {
      this._cycleResolve = resolve;
      this._cycleTimer = setTimeout(() => {
        if (this._cycleResolve) {
          this._cycleResolve(false);
          this._cycleResolve = null;
        }
      }, 5000);
    });
    // Close the gap between the synchronous loss request and the queued event.
    this.ready = false;
    this.lost = true;
    extension.loseContext();
    this._restoreTimer = setTimeout(() => extension.restoreContext(), 650);
    return restored;
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.ready = false;
    clearTimeout(this._cycleTimer);
    clearTimeout(this._restoreTimer);
    if (this._cycleResolve) {
      this._cycleResolve(false);
      this._cycleResolve = null;
    }
    this.canvas.removeEventListener("webglcontextlost", this._handleContextLost);
    this.canvas.removeEventListener("webglcontextrestored", this._handleContextRestored);
    if (!this.gl.isContextLost()) {
      for (const chart of this.charts) {
        destroyPickTarget(this.gl, chart);
        destroyChartGpu(this.gl, chart);
      }
      destroyProgramSet(this.gl, this.programs);
      this.lossExtension?.loseContext();
    }
    this.charts = [];
  }
}

class NativeBackend {
  constructor(app) {
    this.app = app;
    this.mode = "native";
    this.records = [];
  }

  attach(chart) {
    const gl = chart.canvas.getContext("webgl2", {
      alpha: true,
      antialias: false,
      premultipliedAlpha: true,
      preserveDrawingBuffer: false,
    });
    const record = {
      chart,
      gl,
      programs: null,
      generation: 1,
      destroying: false,
      lossExtension: null,
      cycleResolve: null,
      cycleTimer: 0,
      restoreTimer: 0,
    };
    chart.native = record;
    this.records.push(record);
    if (!gl) {
      chart.setState("error", "context denied");
      return;
    }

    chart.canvas.addEventListener("webglcontextlost", (event) => {
      event.preventDefault();
      record.generation += 1;
      record.programs = null;
      chart.gpu = null;
      chart.pickTarget = null;
      if (!record.destroying) {
        chart.setState("lost", "evicted");
        this.app.onContextLost(`Native context ${chart.index + 1} lost.`);
      }
    });

    chart.canvas.addEventListener("webglcontextrestored", () => {
      if (record.destroying) return;
      let rebuilt = false;
      let nextPrograms = null;
      try {
        nextPrograms = createProgramSet(gl);
        record.programs = nextPrograms;
        record.lossExtension = gl.getExtension("WEBGL_lose_context");
        createChartGpu(gl, chart);
        chart.pickTarget = null;
        chart.setState("live");
        this.app.needsDraw = true;
        this.app.onContextRestored(`Native context ${chart.index + 1} restored.`);
        rebuilt = true;
      } catch (error) {
        if (!gl.isContextLost()) {
          destroyChartGpu(gl, chart);
          destroyProgramSet(gl, nextPrograms);
        }
        record.programs = null;
        chart.gpu = null;
        chart.pickTarget = null;
        chart.setState("error", "restore failed");
        this.app.log(`Native chart ${chart.index + 1} restore failed: ${error.message}`);
      }
      clearTimeout(record.cycleTimer);
      clearTimeout(record.restoreTimer);
      record.cycleTimer = 0;
      record.restoreTimer = 0;
      if (record.cycleResolve) {
        record.cycleResolve(rebuilt);
        record.cycleResolve = null;
      }
    });

    try {
      record.programs = createProgramSet(gl);
      record.lossExtension = gl.getExtension("WEBGL_lose_context");
      createChartGpu(gl, chart);
      chart.setState("live");
    } catch (error) {
      if (!gl.isContextLost()) {
        destroyChartGpu(gl, chart);
        destroyProgramSet(gl, record.programs);
      }
      record.programs = null;
      chart.gpu = null;
      chart.pickTarget = null;
      chart.setState("error", gl.isContextLost() ? "evicted" : "init failed");
      this.app.log(`Native chart ${chart.index + 1} initialization: ${error.message}`);
    }
  }

  onResize(chart) {
    const record = chart.native;
    if (!record?.gl || record.gl.isContextLost()) {
      chart.pickTarget = null;
      return;
    }
    destroyPickTarget(record.gl, chart);
  }

  render(chart, time, stressState) {
    const record = chart.native;
    const gl = record?.gl;
    if (!gl || gl.isContextLost() || !record.programs || !chart.gpu) {
      if (chart.card.dataset.state === "live") chart.setState("lost", "evicted");
      return null;
    }
    chart.updateVertices(time);
    chart.frameByte = (chart.frameByte + 1) & 255;
    beginPass(gl, null, chart.pixelWidth, chart.pixelHeight, true);
    const timings = uploadAndDraw(gl, record.programs, chart);
    if (gl.isContextLost()) {
      record.programs = null;
      chart.gpu = null;
      chart.pickTarget = null;
      chart.setState("lost", "evicted");
      return null;
    }
    if (stressState) poisonState(gl, record.programs, chart.pixelWidth, chart.pixelHeight);
    if (gl.isContextLost()) {
      record.programs = null;
      chart.gpu = null;
      chart.pickTarget = null;
      chart.setState("lost", "evicted");
      return null;
    }
    return { ...timings, presentMs: 0 };
  }

  pick(chart, clientX, clientY) {
    const record = chart.native;
    const gl = record?.gl;
    if (!gl || gl.isContextLost() || !record.programs || !chart.gpu) return -1;
    const rect = chart.canvas.getBoundingClientRect();
    const x = ((clientX - rect.left) * chart.pixelWidth) / Math.max(1, rect.width);
    const topRow = Math.floor(
      ((clientY - rect.top) * chart.pixelHeight) / Math.max(1, rect.height),
    );
    const y = chart.pixelHeight - 1 - topRow;
    return pickAtPixel(gl, record.programs, chart, record.generation, x, y);
  }

  pickKnownIndex(chart, index) {
    const record = chart.native;
    const gl = record?.gl;
    if (!gl || gl.isContextLost() || !record.programs || !chart.gpu) return -1;
    const x = chart.vertices[index * 2] * (chart.pixelWidth - 1);
    const yValue = chart.vertices[index * 2 + 1] * chart.yScale;
    const y = (yValue * 0.5 + 0.5) * (chart.pixelHeight - 1);
    return pickAtPixel(gl, record.programs, chart, record.generation, x, y, index, 1);
  }

  inspectCanary(chart) {
    const record = chart.native;
    const gl = record?.gl;
    if (!gl || gl.isContextLost()) return { pass: false, lost: true };
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.readBuffer(gl.BACK);
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
    const topLeft = new Uint8Array(4);
    const bottomRight = new Uint8Array(4);
    gl.readPixels(2, chart.pixelHeight - 3, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, topLeft);
    gl.readPixels(
      chart.pixelWidth - 3,
      2,
      1,
      1,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      bottomRight,
    );
    const id = (chart.index + 1) & 255;
    return {
      pass:
        sampleMatches([...topLeft], [id, chart.frameByte, 17, 255]) &&
        sampleMatches([...bottomRight], [id, chart.frameByte, 239, 255]),
      topLeft: [...topLeft],
      bottomRight: [...bottomRight],
    };
  }

  getStats() {
    const created = this.records.filter((record) => record.gl).length;
    const live = this.getLiveCharts().length;
    return {
      requestedContexts: this.records.length,
      createdContexts: created,
      liveContexts: live,
      liveCharts: live,
      requestedCharts: this.records.length,
      resourceLabel: `${live} sets / ${live} VBOs`,
    };
  }

  getEnvironment() {
    const record = this.records.find((item) => item.gl && !item.gl.isContextLost());
    return record?.gl ? readGlIdentity(record.gl) : null;
  }

  getLiveCharts() {
    return this.records
      .filter(
        (record) =>
          record.gl &&
          !record.gl.isContextLost() &&
          record.programs &&
          record.chart.gpu &&
          record.chart.card.dataset.state === "live",
      )
      .map((record) => record.chart);
  }

  async cycleContext() {
    const record = this.records.find(
      (item) =>
        item.gl &&
        !item.gl.isContextLost() &&
        item.programs &&
        item.chart.gpu &&
        item.chart.card.dataset.state === "live" &&
        item.lossExtension &&
        !item.cycleResolve,
    );
    if (!record) return false;
    const extension = record.lossExtension;
    const restored = new Promise((resolve) => {
      record.cycleResolve = resolve;
      record.cycleTimer = setTimeout(() => {
        record.cycleTimer = 0;
        if (record.cycleResolve) {
          record.cycleResolve(false);
          record.cycleResolve = null;
        }
      }, 5000);
    });
    extension.loseContext();
    record.restoreTimer = setTimeout(() => {
      record.restoreTimer = 0;
      if (!record.destroying) extension.restoreContext();
    }, 650);
    return restored;
  }

  dispose() {
    for (const record of this.records) {
      record.destroying = true;
      clearTimeout(record.cycleTimer);
      clearTimeout(record.restoreTimer);
      record.cycleTimer = 0;
      record.restoreTimer = 0;
      if (record.cycleResolve) {
        record.cycleResolve(false);
        record.cycleResolve = null;
      }
      if (!record.gl || record.gl.isContextLost()) continue;
      destroyPickTarget(record.gl, record.chart);
      destroyChartGpu(record.gl, record.chart);
      destroyProgramSet(record.gl, record.programs);
      record.lossExtension?.loseContext();
    }
    this.records = [];
  }
}

class ExperimentApp {
  constructor() {
    const params = new URLSearchParams(location.search);
    this.mode = params.get("mode") === "native" ? "native" : "shared";
    const countParam = params.get("count");
    const requestedCount = countParam?.trim() ? Number(countParam) : 50;
    this.count = clamp(
      Number.isFinite(requestedCount) ? Math.trunc(requestedCount) : 50,
      1,
      50,
    );
    this.backend = null;
    this.charts = [];
    this.rebuilding = false;
    this.activeOperation = null;
    this.needsDraw = true;
    this.frameSamples = createSampleBuffer();
    this.presentSamples = createSampleBuffer();
    this.uploadSamples = createSampleBuffer();
    this.drawSamples = createSampleBuffer();
    this.frameCountWindow = 0;
    this.fpsObserved = 0;
    this.fpsWindowStart = performance.now();
    this.lastFrameAt = 0;
    this.lastMetricsAt = 0;
    this.presentationsTotal = 0;
    this.productiveBatchesTotal = 0;
    this.contextLosses = 0;
    this.contextRestores = 0;
    this.lastCheck = null;
    this._resizeScheduled = false;
    this.lastDpr = Math.min(MAX_DPR, window.devicePixelRatio || 1);
    this.statusHoldUntil = 0;

    this.ui = {
      mode: $("#mode"),
      count: $("#count"),
      countOutput: $("#count-output"),
      fpsTarget: $("#fps-target"),
      streaming: $("#streaming"),
      poisonState: $("#poison-state"),
      dense: $("#dense"),
      verify: $("#verify"),
      benchmark: $("#benchmark"),
      cycle: $("#cycle-context"),
      grid: $("#chart-grid"),
      status: $("#status"),
      lastCheck: $("#last-check"),
      health: $("#health-dot"),
      log: $("#log"),
      contexts: $("#metric-contexts"),
      contextsNote: $("#metric-contexts-note"),
      live: $("#metric-live"),
      liveNote: $("#metric-live-note"),
      fps: $("#metric-fps"),
      frame: $("#metric-frame"),
      present: $("#metric-present"),
      resources: $("#metric-resources"),
    };

    this.ui.mode.value = this.mode;
    this.ui.count.value = String(this.count);
    this.ui.countOutput.value = String(this.count);
    this.bindControls();
  }

  log(message, data = null) {
    const timestamp = new Date().toLocaleTimeString([], { hour12: false });
    const suffix = data ? `\n${JSON.stringify(data, null, 2)}` : "";
    this.ui.log.textContent = `[${timestamp}] ${message}${suffix}\n${this.ui.log.textContent}`;
  }

  setStatus(message, state = "working", holdMilliseconds = 0) {
    if (this.ui.status.textContent !== message) this.ui.status.textContent = message;
    if (this.ui.health.dataset.state !== state) this.ui.health.dataset.state = state;
    if (holdMilliseconds > 0) {
      this.statusHoldUntil = performance.now() + holdMilliseconds;
    }
  }

  beginOperation(name) {
    if (this.activeOperation) {
      this.log(`Skipped ${name}; ${this.activeOperation} is already running.`);
      return false;
    }
    this.activeOperation = name;
    this.ui.verify.disabled = true;
    this.ui.benchmark.disabled = true;
    this.ui.cycle.disabled = true;
    return true;
  }

  endOperation(name) {
    if (this.activeOperation !== name) return;
    this.activeOperation = null;
    this.ui.verify.disabled = false;
    this.ui.benchmark.disabled = false;
    this.ui.cycle.disabled = false;
  }

  onContextLost(message) {
    this.contextLosses += 1;
    this.setStatus(message, "working");
    this.log(message);
  }

  onContextRestored(message) {
    this.contextRestores += 1;
    this.setStatus(message, "pass");
    this.log(message);
  }

  bindControls() {
    this.ui.mode.addEventListener("change", () => this.navigate({ mode: this.ui.mode.value }));
    this.ui.count.addEventListener("input", () => {
      this.ui.countOutput.value = this.ui.count.value;
    });
    this.ui.count.addEventListener("change", () => {
      this.navigate({ count: Number(this.ui.count.value) });
    });
    this.ui.streaming.addEventListener("change", () => {
      this.needsDraw = true;
    });
    this.ui.poisonState.addEventListener("change", () => {
      this.needsDraw = true;
      this.log(`State stress ${this.ui.poisonState.checked ? "enabled" : "disabled"}.`);
    });
    this.ui.dense.addEventListener("change", async () => {
      this.ui.grid.classList.toggle("chart-grid--dense", this.ui.dense.checked);
      await nextFrame();
      await nextFrame();
      this.resizeAll();
    });
    this.ui.verify.addEventListener("click", () => this.verify());
    this.ui.benchmark.addEventListener("click", () => this.benchmark(3000));
    this.ui.cycle.addEventListener("click", () => this.cycleContext());
  }

  navigate(changes) {
    const params = new URLSearchParams(location.search);
    params.set("mode", changes.mode || this.mode);
    params.set("count", String(changes.count ?? this.count));
    this.resizeObserver?.disconnect();
    this.backend?.dispose();
    this.backend = null;
    location.search = params.toString();
  }

  async init() {
    this.rebuilding = true;
    this.setStatus(`Building ${this.mode} renderer…`, "working");
    this.ui.grid.replaceChildren();
    this.ui.grid.classList.toggle("chart-grid--dense", this.ui.dense.checked);
    const fragment = document.createDocumentFragment();
    for (let index = 0; index < this.count; index += 1) {
      const chart = new ChartView(index, this);
      this.charts.push(chart);
      fragment.append(chart.card);
    }
    this.ui.grid.append(fragment);
    await nextFrame();
    this.resizeAll(false);

    try {
      this.backend = this.mode === "shared" ? new SharedBackend(this) : new NativeBackend(this);
      for (const chart of this.charts) this.backend.attach(chart);
    } catch (error) {
      try {
        this.backend?.dispose();
      } catch (disposeError) {
        this.log("Renderer cleanup failed.", { message: disposeError.message });
      }
      this.backend = null;
      this.setStatus(error.message, "fail");
      this.log("Renderer initialization failed.", { message: error.message, stack: error.stack });
      this.rebuilding = false;
      window.__EXPERIMENT_READY = false;
      return;
    }

    this.resizeObserver = new ResizeObserver(() => {
      if (this._resizeScheduled) return;
      this._resizeScheduled = true;
      requestAnimationFrame(() => {
        this._resizeScheduled = false;
        this.resizeAll();
      });
    });
    this.resizeObserver.observe(this.ui.grid);

    this.rebuilding = false;
    this.needsDraw = true;
    this.log(
      this.mode === "shared"
        ? `Shared mode ready: ${this.count} charts, one WebGL2 context.`
        : `Native mode requested ${this.count} independent WebGL2 contexts.`,
    );
    this.log("Browser environment.", {
      userAgent: navigator.userAgent,
      platform: navigator.platform,
      webgl: this.backend.getEnvironment?.() || null,
    });
    window.__EXPERIMENT_READY = true;
    requestAnimationFrame((time) => this.loop(time));
    await nextFrame();
    this.updateMetrics(true);
  }

  resizeAll(markDirty = true) {
    for (const chart of this.charts) {
      if (chart.resize() && this.backend) this.backend.onResize(chart);
    }
    if (markDirty) this.needsDraw = true;
  }

  loop(now) {
    requestAnimationFrame((time) => this.loop(time));
    if (this.rebuilding || !this.backend) return;
    const currentDpr = Math.min(MAX_DPR, window.devicePixelRatio || 1);
    if (currentDpr !== this.lastDpr) {
      this.lastDpr = currentDpr;
      this.resizeAll();
    }
    const targetFps = Number(this.ui.fpsTarget.value) || 60;
    const interval = 1000 / targetFps;
    const shouldDraw = this.ui.streaming.checked || this.needsDraw;
    if (!shouldDraw || now - this.lastFrameAt < interval - 1) {
      if (now - this.lastMetricsAt > 250) this.updateMetrics();
      return;
    }

    this.lastFrameAt = now;
    this.needsDraw = false;
    const time = now / 1000;
    const frameStart = performance.now();
    let presentations = 0;
    for (const chart of this.charts) {
      const timing = this.backend.render(chart, time, this.ui.poisonState.checked);
      if (!timing) continue;
      presentations += 1;
      pushSample(this.uploadSamples, timing.uploadMs);
      pushSample(this.drawSamples, timing.drawMs);
      if (this.mode === "shared") pushSample(this.presentSamples, timing.presentMs);
    }
    if (presentations > 0) {
      pushSample(this.frameSamples, performance.now() - frameStart);
      this.presentationsTotal += presentations;
      this.productiveBatchesTotal += 1;
      this.frameCountWindow += 1;
    }

    if (now - this.fpsWindowStart >= 1000) {
      this.fpsObserved = (this.frameCountWindow * 1000) / (now - this.fpsWindowStart);
      this.frameCountWindow = 0;
      this.fpsWindowStart = now;
    }
    if (now - this.lastMetricsAt > 250) this.updateMetrics();
  }

  updateMetrics(force = false) {
    if (!this.backend) return;
    const now = performance.now();
    if (!force && now - this.lastMetricsAt < 200) return;
    this.lastMetricsAt = now;
    const stats = this.backend.getStats();
    const fullyLive = stats.liveCharts === stats.requestedCharts;

    if (this.mode === "shared") {
      this.ui.contexts.textContent = String(stats.liveContexts);
      this.ui.contextsNote.textContent = "one document-level host";
    } else {
      this.ui.contexts.textContent = `${stats.liveContexts} / ${stats.requestedContexts}`;
      this.ui.contextsNote.textContent = `${stats.createdContexts} created; browser governs survival`;
    }
    this.ui.live.textContent = `${stats.liveCharts} / ${stats.requestedCharts}`;
    this.ui.liveNote.textContent = fullyLive ? "all charts updating" : "some charts lost or unavailable";
    this.ui.fps.textContent = this.fpsObserved ? this.fpsObserved.toFixed(1) : "—";
    this.ui.frame.textContent = formatMs(percentile(this.frameSamples, 0.95));
    this.ui.present.textContent =
      this.mode === "shared" ? formatMs(percentile(this.presentSamples, 0.95)) : "none";
    this.ui.resources.textContent = stats.resourceLabel;

    if (now >= this.statusHoldUntil) {
      if (this.mode === "shared") {
        this.setStatus(
          fullyLive
            ? `${stats.liveCharts} charts are live through one real WebGL2 context.`
            : `Shared host currently has ${stats.liveCharts}/${stats.requestedCharts} live charts.`,
          fullyLive ? "pass" : "working",
        );
      } else {
        this.setStatus(
          fullyLive
            ? `All ${stats.liveCharts} native contexts remain live.`
            : `Native ceiling observed: ${stats.liveCharts}/${stats.requestedCharts} contexts remain live.`,
          fullyLive ? "pass" : "working",
        );
      }
    }
  }

  pick(chart, clientX, clientY) {
    if (!this.backend || this.rebuilding) return;
    try {
      const index = this.backend.pick(chart, clientX, clientY);
      chart.showPick(index, clientX, clientY);
    } catch (error) {
      chart.tooltip.dataset.show = "false";
      this.log(`Pick failed on chart ${chart.index + 1}: ${error.message}`);
    }
  }

  async verify() {
    if (!this.backend || this.rebuilding || !this.beginOperation("verify")) return null;
    try {
      return await this.runVerification();
    } finally {
      this.endOperation("verify");
    }
  }

  async runVerification({ charts = this.charts, requireFullAvailability = true } = {}) {
    const wasStreaming = this.ui.streaming.checked;
    this.ui.streaming.checked = false;
    const fixedTime = 2.375;
    const canaryFailures = [];
    const pickFailures = [];
    const renderedCharts = [];
    let rendered = 0;

    try {
      const verificationSetup =
        this.backend.prepareVerification?.(charts[0]) || { cropOffsetPixels: 0 };

      // Native charts own independent contexts, so each one needs a priming draw
      // that leaves its context poisoned before the draw whose canary is inspected.
      if (this.mode === "native") {
        for (const chart of charts) this.backend.render(chart, fixedTime, true);
      }

      for (const chart of charts) {
        const timing = this.backend.render(chart, fixedTime, true);
        if (!timing) continue;
        rendered += 1;
        renderedCharts.push(chart);
        const inspection = this.backend.inspectCanary(chart);
        if (!inspection.pass) {
          canaryFailures.push({ chart: chart.index + 1, ...inspection });
        }
      }

      const testCharts = renderedCharts;
      const indices = [128, 512, 896];
      for (const chart of testCharts) {
        for (const expected of indices) {
          const actual = this.backend.pickKnownIndex(chart, expected);
          if (actual !== expected) {
            pickFailures.push({ chart: chart.index + 1, expected, actual });
          }
        }
      }

      const stats = this.backend.getStats();
      const fullyLive = stats.liveCharts === stats.requestedCharts;
      const expectedCharts = charts.length;
      const currentLiveCharts =
        this.backend.getLiveCharts?.() ||
        this.charts.filter((chart) => chart.card.dataset.state === "live");
      const currentLiveSet = new Set(currentLiveCharts);
      // Recovery is scoped to the charts that were live before the cycle. An
      // unrelated context reviving concurrently must not make that recovery fail.
      const liveSetMatches = charts.every((chart) => currentLiveSet.has(chart));
      const availabilityPass = requireFullAvailability ? fullyLive : liveSetMatches;
      const contextInvariant = this.mode !== "shared" || stats.liveContexts === 1;
      const coherentLiveSet = requireFullAvailability
        ? rendered === stats.liveCharts
        : rendered === expectedCharts && liveSetMatches;
      const coverageComplete =
        rendered === expectedCharts && testCharts.length === expectedCharts;
      const pass =
        availabilityPass &&
        contextInvariant &&
        coherentLiveSet &&
        coverageComplete &&
        canaryFailures.length === 0 &&
        pickFailures.length === 0;
      this.lastCheck = {
        pass,
        mode: this.mode,
        requestedCharts: stats.requestedCharts,
        liveCharts: stats.liveCharts,
        fullyLive,
        expectedCharts,
        requireFullAvailability,
        liveSetMatches,
        liveContexts: stats.liveContexts,
        contextInvariant,
        coherentLiveSet,
        coverageComplete,
        canaryChecks: rendered,
        canaryFailures,
        pickChecks: testCharts.length * indices.length,
        pickFailures,
        cropOffsetPixels: verificationSetup.cropOffsetPixels,
        stateStress: true,
        dpr: this.charts[0]?.dpr || 1,
        timestamp: new Date().toISOString(),
      };
      window.__LAST_CHECK = this.lastCheck;
      window.__EXPERIMENT_DONE = true;
      const missingCharts = Math.max(0, expectedCharts - rendered);
      this.ui.lastCheck.textContent = pass
        ? `PASS · ${rendered} canaries · ${this.lastCheck.pickChecks} picks`
        : `FAIL · ${missingCharts} unavailable · ${canaryFailures.length} canary · ${pickFailures.length} pick`;
      this.setStatus(
        pass
          ? requireFullAvailability
            ? `Checks passed: isolated frames, orientation, state reset, and picking are correct.`
            : `Recovery checks passed for all ${expectedCharts} pre-cycle live charts.`
          : `${requireFullAvailability ? "Checks" : "Recovery checks"} failed: ` +
            `${missingCharts} expected chart(s) unavailable, ${
              canaryFailures.length + pickFailures.length
            } rendering issue(s).`,
        pass ? "pass" : "fail",
        4000,
      );
      const checkLabel = requireFullAvailability ? "Correctness" : "Recovery";
      this.log(`${checkLabel} checks ${pass ? "passed" : "failed"}.`, this.lastCheck);
      return this.lastCheck;
    } finally {
      this.ui.streaming.checked = wasStreaming;
      this.needsDraw = true;
    }
  }

  async benchmark(milliseconds = 3000) {
    if (!this.backend || this.rebuilding || !this.beginOperation("benchmark")) return null;
    const wasStreaming = this.ui.streaming.checked;
    try {
      const requestedDurationMs = milliseconds;
      this.ui.streaming.checked = true;
      clearSamples(this.frameSamples);
      clearSamples(this.presentSamples);
      clearSamples(this.uploadSamples);
      clearSamples(this.drawSamples);
      const startPresentations = this.presentationsTotal;
      const startBatches = this.productiveBatchesTotal;
      const startLosses = this.contextLosses;
      const startRestores = this.contextRestores;
      const start = performance.now();
      this.setStatus(
        `Benchmarking ${this.mode} mode for ${(milliseconds / 1000).toFixed(1)}s…`,
      );
      await wait(requestedDurationMs);
      const elapsed = performance.now() - start;
      const stats = this.backend.getStats();
      const productiveBatches = this.productiveBatchesTotal - startBatches;
      const targetFps = Number(this.ui.fpsTarget.value) || 60;
      const expectedBatches = Math.floor((elapsed * targetFps) / 1000);
      const chartPresentations = this.presentationsTotal - startPresentations;
      const chartSizes = this.charts.map((chart) => [chart.pixelWidth, chart.pixelHeight]);
      const result = {
        mode: this.mode,
        requestedDurationMs,
        durationMs: elapsed,
        requestedCharts: stats.requestedCharts,
        liveCharts: stats.liveCharts,
        fullyLive: stats.liveCharts === stats.requestedCharts,
        liveContexts: stats.liveContexts,
        targetFps,
        observedFps: (productiveBatches * 1000) / Math.max(1, elapsed),
        productiveBatches,
        expectedBatches,
        droppedIntervals: Math.max(0, expectedBatches - productiveBatches),
        chartPresentations,
        chartPresentationsPerSecond:
          (chartPresentations * 1000) / Math.max(1, elapsed),
        frameMs: {
          p50: percentile(this.frameSamples, 0.5),
          p95: percentile(this.frameSamples, 0.95),
          p99: percentile(this.frameSamples, 0.99),
        },
        uploadMsPerChart: {
          p50: percentile(this.uploadSamples, 0.5),
          p95: percentile(this.uploadSamples, 0.95),
        },
        drawMsPerChart: {
          p50: percentile(this.drawSamples, 0.5),
          p95: percentile(this.drawSamples, 0.95),
        },
        presentMsPerChart:
          this.mode === "shared"
            ? {
                p50: percentile(this.presentSamples, 0.5),
                p95: percentile(this.presentSamples, 0.95),
              }
            : null,
        stateStress: this.ui.poisonState.checked,
        timingScope: "JavaScript CPU submission; not completed GPU execution",
        environment: {
          userAgent: navigator.userAgent,
          platform: navigator.platform,
          webgl: this.backend.getEnvironment?.() || null,
        },
        pointsPerChart: POINT_COUNT,
        dpr: this.charts[0]?.dpr || 1,
        canvasPixels: {
          minWidth: Math.min(...chartSizes.map(([width]) => width)),
          maxWidth: Math.max(...chartSizes.map(([width]) => width)),
          minHeight: Math.min(...chartSizes.map(([, height]) => height)),
          maxHeight: Math.max(...chartSizes.map(([, height]) => height)),
        },
        viewportCssPixels: { width: innerWidth, height: innerHeight },
        dense: this.ui.dense.checked,
        contextLossesDuringRun: this.contextLosses - startLosses,
        contextRestoresDuringRun: this.contextRestores - startRestores,
        timestamp: new Date().toISOString(),
      };
      window.__LAST_BENCHMARK = result;
      this.ui.lastCheck.textContent =
        `BENCH · p95 ${result.frameMs.p95.toFixed(2)} ms · ` +
        `${result.chartPresentationsPerSecond.toFixed(0)} presentations/s`;
      this.setStatus(
        `Benchmark complete: p95 ${result.frameMs.p95.toFixed(2)} ms, ` +
          `${result.chartPresentationsPerSecond.toFixed(0)} chart presentations/s.`,
        result.fullyLive ? "pass" : "working",
        4000,
      );
      this.log("Benchmark complete.", result);
      return result;
    } finally {
      this.ui.streaming.checked = wasStreaming;
      this.needsDraw = true;
      this.endOperation("benchmark");
    }
  }

  async cycleContext() {
    if (!this.backend || this.rebuilding || !this.beginOperation("cycle")) return false;
    try {
      const recoveryCharts =
        this.mode === "native" ? this.backend.getLiveCharts() : this.charts;
      this.setStatus(
        this.mode === "shared"
          ? "Losing the one shared context; every client should pause together…"
          : "Losing one native context; peer charts should continue…",
      );
      const restored = await this.backend.cycleContext();
      await nextFrame();
      await nextFrame();
      if (!restored) {
        this.setStatus(
          "Context-loss extension unavailable or restoration timed out.",
          "fail",
          4000,
        );
        return false;
      }
      this.needsDraw = true;
      await nextFrame();
      const check = await this.runVerification({
        charts: recoveryCharts,
        requireFullAvailability: this.mode === "shared",
      });
      return Boolean(check?.pass);
    } finally {
      this.endOperation("cycle");
    }
  }

  snapshot() {
    return {
      mode: this.mode,
      count: this.count,
      ready: Boolean(window.__EXPERIMENT_READY),
      stats: this.backend?.getStats() || null,
      observedFps: this.fpsObserved,
      frameP95Ms: percentile(this.frameSamples, 0.95),
      presentP95Ms:
        this.mode === "shared" ? percentile(this.presentSamples, 0.95) : null,
      contextLosses: this.contextLosses,
      contextRestores: this.contextRestores,
      lastCheck: this.lastCheck,
    };
  }
}

const app = new ExperimentApp();

window.__EXPERIMENT_READY = false;
window.__EXPERIMENT_DONE = false;
window.__sharedWebglExperiment = {
  snapshot: () => app.snapshot(),
  verify: () => app.verify(),
  benchmark: (milliseconds = 3000) => app.benchmark(milliseconds),
  cycleContext: () => app.cycleContext(),
  setMode: (mode) => app.navigate({ mode }),
  setCount: (count) => app.navigate({ count }),
};

app.init();
