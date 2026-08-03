import { ATTR_SLOTS } from "./40_gl";

// ---------------------------------------------------------------------------
// Shared WebGL2 host
// ---------------------------------------------------------------------------

/** The lifecycle surface a ChartView exposes to the shared host.  The methods
 * are optional so acquisition can happen before the prototype-augmentation
 * modules have installed every lifecycle hook. */
export interface GLHostClient {
  _onGlHostContextLost?: () => void;
  _onGlHostContextRestored?: () => void;
}

type DrawCallback<T> = (gl: WebGL2RenderingContext) => T;

type GLHostSurface = {
  canvas: HTMLCanvasElement;
  gl: WebGL2RenderingContext;
  maxViewport: [number, number];
  maxVertexAttribs: number;
};

type SharedQuad = {
  quad: WebGLBuffer;
  vao: WebGLVertexArrayObject;
};

// `Symbol.for` makes the registry survive duplicate evaluations of the same
// bundle in one realm (notebook/widget hosts commonly create distinct module
// URLs for identical source).  The protocol suffix deliberately prevents a
// future incompatible GLHost implementation from sharing private state with
// this one; bump it when the host/client contract changes incompatibly.
const HOST_REGISTRY_KEY = Symbol.for("reflex-dev.xy.shared-webgl-host.v1");

function sharedHostRegistry(): WeakMap<Document, GLHost> {
  const scope = globalThis as typeof globalThis & Record<PropertyKey, unknown>;
  const existing = scope[HOST_REGISTRY_KEY];
  if (existing instanceof WeakMap) return existing as WeakMap<Document, GLHost>;
  const registry = new WeakMap<Document, GLHost>();
  try {
    Object.defineProperty(scope, HOST_REGISTRY_KEY, {
      value: registry,
      configurable: true,
      enumerable: false,
      writable: false,
    });
  } catch (_error) {
    // A hardened/frozen global cannot host a cross-evaluation registry. Keep a
    // functional module-local fallback instead of making rendering fail.
  }
  const installed = scope[HOST_REGISTRY_KEY];
  return installed instanceof WeakMap
    ? installed as WeakMap<Document, GLHost>
    : registry;
}

const HOSTS = sharedHostRegistry();

// The production renderer currently binds texture units 0 and 1.  Keeping the
// boundary explicit makes adding a third unit a reviewed state-contract change
// instead of letting one virtual client silently leak a binding into another.
const XY_TEXTURE_UNITS = 2;
const XY_UNIFORM_BUFFER_BINDINGS = 4;
const RECOVERY_INITIAL_DELAY_MS = 250;
const RECOVERY_MAX_DELAY_MS = 4000;

function sharedHostEnabled(doc: Document): boolean {
  const win = doc && doc.defaultView;
  if (!win) return false;
  const override = (win as Window & { XY_SHARED_WEBGL?: unknown }).XY_SHARED_WEBGL;
  if (typeof override === "boolean") return override;
  // One module instance is one document.  Enabling by default inside every
  // iframe would merely replace N chart contexts with N frame contexts and
  // would still consume the browser's process-wide context budget.
  try {
    return win.top === win;
  } catch (_error) {
    return false;
  }
}

function pixelExtent(value: number): number {
  const n = Math.floor(Number(value));
  return Number.isFinite(n) && n > 0 ? n : 0;
}

/** One detached canvas/context shared by every participating view in a
 * document. Client GPU objects, linked programs, and mutable uniforms remain
 * client-owned; the immutable fullscreen grid quad and compiled shaders are
 * pooled here for the lifetime of one context generation. */
export class GLHost {
  canvas: HTMLCanvasElement;
  gl: WebGL2RenderingContext;

  sharedQuad: WebGLBuffer | null = null;
  sharedQuadVao: WebGLVertexArrayObject | null = null;
  generation = 1;
  lost = false;
  ready = false;

  private readonly _clients = new Set<GLHostClient>();
  private _maxViewport: [number, number];
  private _maxVertexAttribs: number;
  private _capacityWidth = 1;
  private _capacityHeight = 1;
  private _activeClient: GLHostClient | null = null;
  private readonly _shaderCache = new Map<number, Map<string, WebGLShader>>();
  private _disposed = false;
  private _recoveryTimer: ReturnType<typeof setTimeout> | null = null;
  private _recoveryDelay = RECOVERY_INITIAL_DELAY_MS;
  private readonly _doc: Document;
  private readonly _onDispose: () => void;

  private readonly _handleContextLost = (event: Event) => {
    event.preventDefault();
    if (this._disposed) return;
    this._markLost();
  };

  private readonly _handleContextRestored = () => {
    if (this._disposed) return;
    this._clearRecoveryTimer();
    if (this.gl.isContextLost()) {
      this._markLost();
      return;
    }
    try {
      // A restored context has a fresh object namespace even when the canvas
      // and WebGLRenderingContext identity did not change.
      this._dropShaderHandles();
      this._createSharedQuad();
      this.lost = false;
      this.ready = true;
    } catch (error) {
      this._markLost();
      console.error("xy: shared WebGL host restore failed", error);
      return;
    }
    this._recoveryDelay = RECOVERY_INITIAL_DELAY_MS;
    this._notify("_onGlHostContextRestored");
    // A client can lose the host again while rebuilding its own resources.
    if (this.gl.isContextLost()) this._markLost();
  };

  constructor(doc: Document, onDispose: () => void) {
    this._doc = doc;
    this._onDispose = onDispose;
    const surface = this._createSurface();
    this.canvas = surface.canvas;
    this.gl = surface.gl;
    this._maxViewport = surface.maxViewport;
    this._maxVertexAttribs = surface.maxVertexAttribs;

    this._attachSurfaceListeners(this.canvas);
    try {
      this._createSharedQuad();
      this.ready = true;
    } catch (error) {
      this._detachSurfaceListeners(this.canvas);
      try { this.gl.getExtension("WEBGL_lose_context")?.loseContext(); } catch (_cleanupError) {}
      throw error;
    }
  }

  /** Registering is intentionally internal to acquireGLHost: callers cannot
   * obtain an uncounted live host that would never be disposed. */
  _register(client: GLHostClient): void {
    if (this._disposed) throw new Error("xy: shared WebGL host is disposed");
    this._clients.add(client);
  }

  /** Resolve one immutable compiled shader for this host context. Programs
   * remain client-owned because their uniforms are mutable. This method is an
   * additive capability: ChartView checks for it at runtime so a v1 host from
   * an older duplicate bundle safely retains per-program compilation. */
  getOrCreateShader(type: number, source: string): WebGLShader {
    if (this._disposed || !this.ready || this.lost) {
      throw new Error("xy: shared WebGL host is unavailable for shader compilation");
    }
    const gl = this.gl;
    if (gl.isContextLost()) {
      this._markLost();
      throw new Error("xy: shared WebGL host context lost during shader compilation");
    }

    let shaders = this._shaderCache.get(type);
    const cached = shaders?.get(source);
    if (cached) return cached;

    const shader = gl.createShader(type);
    if (!shader) throw new Error("xy: could not allocate shared WebGL shader");
    try {
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      const ok = gl.getShaderParameter(shader, gl.COMPILE_STATUS);
      const info = gl.getShaderInfoLog(shader);
      if (gl.isContextLost()) {
        this._markLost();
        throw new Error("xy: shared WebGL host context lost during shader compilation");
      }
      if (!ok) throw new Error("shader compile: " + info + "\n" + source);
    } catch (error) {
      // Publish only a successfully compiled shader. A later retry therefore
      // cannot observe a partial/failed cache entry.
      if (!gl.isContextLost()) gl.deleteShader(shader);
      throw error;
    }

    if (!shaders) {
      shaders = new Map<string, WebGLShader>();
      this._shaderCache.set(type, shaders);
    }
    shaders.set(source, shader);
    return shader;
  }

  /** Run one color pass in the bottom-left of the grow-only host buffer and
   * synchronously copy precisely that rectangle into the client's 2D canvas. */
  render<T>(
    client: GLHostClient,
    target2d: CanvasRenderingContext2D,
    width: number,
    height: number,
    drawFn: DrawCallback<T>,
  ): boolean {
    const w = pixelExtent(width);
    const h = pixelExtent(height);
    if (!w || !h || !this._canRun(client)) return false;
    this._enter(client);
    try {
      this._ensureCapacity(w, h);
      if (!this._canRun(client)) return false;
      this._resetPass(null, w, h, true);
      drawFn(this.gl);
      if (this.gl.isContextLost()) {
        this._markLost();
        return false;
      }

      // CanvasImageSource coordinates are top-left based while the GL viewport
      // occupies the host drawing buffer's bottom-left corner.
      const sourceY = this.canvas.height - h;
      target2d.save();
      try {
        target2d.setTransform(1, 0, 0, 1, 0, 0);
        target2d.globalAlpha = 1;
        target2d.globalCompositeOperation = "copy";
        target2d.drawImage(this.canvas, 0, sourceY, w, h, 0, 0, w, h);
      } finally {
        target2d.restore();
      }
      return true;
    } finally {
      this._leave(client);
    }
  }

  /** Run a pick-buffer pass.  Reading must happen inside drawFn (or after the
   * caller explicitly re-binds the FBO); the host restores the default target
   * when the synchronous pass ends. */
  pick<T>(
    client: GLHostClient,
    framebuffer: WebGLFramebuffer,
    width: number,
    height: number,
    drawFn: DrawCallback<T>,
  ): T | null {
    const w = pixelExtent(width);
    const h = pixelExtent(height);
    if (!w || !h || !framebuffer || !this._canRun(client)) return null;
    this._enter(client);
    try {
      this._resetPass(framebuffer, w, h, false);
      const result = drawFn(this.gl);
      if (this.gl.isContextLost()) {
        this._markLost();
        return null;
      }
      return result;
    } finally {
      if (!this.gl.isContextLost()) this.gl.bindFramebuffer(this.gl.FRAMEBUFFER, null);
      this._leave(client);
    }
  }

  /** Drop one client.  The context and all shared objects are released only
   * when the final registered ChartView leaves. */
  release(client: GLHostClient): void {
    if (this._disposed || !this._clients.delete(client)) return;
    if (this._activeClient === client) this._activeClient = null;
    if (this._clients.size === 0) this._dispose();
  }

  private _canRun(client: GLHostClient): boolean {
    if (this._disposed || !this._clients.has(client) || !this.ready || this.lost) return false;
    if (this.gl.isContextLost()) {
      this._markLost();
      return false;
    }
    return true;
  }

  private _enter(client: GLHostClient): void {
    if (this._activeClient) {
      throw new Error("xy: re-entrant shared WebGL pass");
    }
    this._activeClient = client;
  }

  private _leave(client: GLHostClient): void {
    if (this._activeClient === client) this._activeClient = null;
  }

  private _createSurface(): GLHostSurface {
    const canvas = this._doc.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const gl = canvas.getContext("webgl2", {
      alpha: true,
      antialias: false,
      premultipliedAlpha: true,
      // Presentation copies synchronously into client-owned Canvas2D surfaces.
      // Keeping this one host buffer avoids browser-specific discarded-buffer
      // behavior without multiplying the allocation per chart.
      preserveDrawingBuffer: true,
    });
    if (!gl) throw new Error("xy: WebGL2 is unavailable for the shared renderer");
    const maxViewport = gl.getParameter(gl.MAX_VIEWPORT_DIMS);
    return {
      canvas,
      gl,
      maxViewport: [Number(maxViewport[0]), Number(maxViewport[1])],
      maxVertexAttribs: Number(gl.getParameter(gl.MAX_VERTEX_ATTRIBS)),
    };
  }

  private _attachSurfaceListeners(canvas: HTMLCanvasElement): void {
    canvas.addEventListener("webglcontextlost", this._handleContextLost);
    canvas.addEventListener("webglcontextrestored", this._handleContextRestored);
  }

  private _detachSurfaceListeners(canvas: HTMLCanvasElement): void {
    canvas.removeEventListener("webglcontextlost", this._handleContextLost);
    canvas.removeEventListener("webglcontextrestored", this._handleContextRestored);
  }

  private _ensureCapacity(width: number, height: number): void {
    if (width > this._maxViewport[0] || height > this._maxViewport[1]) {
      throw new RangeError(
        `xy: shared WebGL viewport ${width}x${height} exceeds ` +
        `${this._maxViewport[0]}x${this._maxViewport[1]}`,
      );
    }
    const nextWidth = Math.max(this._capacityWidth, width);
    const nextHeight = Math.max(this._capacityHeight, height);
    if (nextWidth === this._capacityWidth && nextHeight === this._capacityHeight) return;
    this._capacityWidth = nextWidth;
    this._capacityHeight = nextHeight;
    this.canvas.width = nextWidth;
    this.canvas.height = nextHeight;
  }

  private _resetPass(
    framebuffer: WebGLFramebuffer | null,
    width: number,
    height: number,
    blend: boolean,
  ): void {
    const gl = this.gl;
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
    // Native ChartView contexts retain WebGL's default dithering behavior.
    gl.enable(gl.DITHER);
    gl.frontFace(gl.CCW);
    gl.cullFace(gl.BACK);
    gl.depthFunc(gl.LESS);
    gl.depthRange(0, 1);
    gl.colorMask(true, true, true, true);
    gl.depthMask(true);
    gl.stencilMaskSeparate(gl.FRONT, 0xffffffff);
    gl.stencilMaskSeparate(gl.BACK, 0xffffffff);
    gl.stencilFuncSeparate(gl.FRONT, gl.ALWAYS, 0, 0xffffffff);
    gl.stencilFuncSeparate(gl.BACK, gl.ALWAYS, 0, 0xffffffff);
    gl.stencilOpSeparate(gl.FRONT, gl.KEEP, gl.KEEP, gl.KEEP);
    gl.stencilOpSeparate(gl.BACK, gl.KEEP, gl.KEEP, gl.KEEP);
    gl.polygonOffset(0, 0);
    gl.clearDepth(1);
    gl.clearStencil(0);
    gl.blendColor(0, 0, 0, 0);
    gl.blendEquation(gl.FUNC_ADD);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    if (blend) gl.enable(gl.BLEND);
    else gl.disable(gl.BLEND);

    for (let unit = 0; unit < XY_TEXTURE_UNITS; unit++) {
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, null);
      gl.bindSampler(unit, null);
    }
    gl.activeTexture(gl.TEXTURE0);

    gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, null);
    gl.bindVertexArray(null);
    for (let slot = 0; slot < this._maxVertexAttribs; slot++) {
      gl.disableVertexAttribArray(slot);
      gl.vertexAttribDivisor(slot, 0);
      gl.vertexAttrib4f(slot, 0, 0, 0, 1);
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, null);
    for (let binding = 0; binding < XY_UNIFORM_BUFFER_BINDINGS; binding++) {
      gl.bindBufferBase(gl.UNIFORM_BUFFER, binding, null);
    }
    gl.bindBuffer(gl.UNIFORM_BUFFER, null);
    gl.bindBuffer(gl.PIXEL_PACK_BUFFER, null);
    gl.bindBuffer(gl.PIXEL_UNPACK_BUFFER, null);
    gl.bindRenderbuffer(gl.RENDERBUFFER, null);

    gl.pixelStorei(gl.PACK_ALIGNMENT, 4);
    gl.pixelStorei(gl.PACK_ROW_LENGTH, 0);
    gl.pixelStorei(gl.PACK_SKIP_PIXELS, 0);
    gl.pixelStorei(gl.PACK_SKIP_ROWS, 0);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
    gl.pixelStorei(gl.UNPACK_ROW_LENGTH, 0);
    gl.pixelStorei(gl.UNPACK_IMAGE_HEIGHT, 0);
    gl.pixelStorei(gl.UNPACK_SKIP_PIXELS, 0);
    gl.pixelStorei(gl.UNPACK_SKIP_ROWS, 0);
    gl.pixelStorei(gl.UNPACK_SKIP_IMAGES, 0);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.BROWSER_DEFAULT_WEBGL);
    gl.useProgram(null);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }

  private _buildSharedQuad(gl: WebGL2RenderingContext): SharedQuad {
    let quad: WebGLBuffer | null = null;
    let vao: WebGLVertexArrayObject | null = null;
    try {
      quad = gl.createBuffer();
      if (!quad) throw new Error("xy: could not create shared fullscreen quad buffer");
      gl.bindBuffer(gl.ARRAY_BUFFER, quad);
      gl.bufferData(
        gl.ARRAY_BUFFER,
        new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]),
        gl.STATIC_DRAW,
      );
      vao = gl.createVertexArray();
      if (!vao) throw new Error("xy: could not create shared fullscreen quad VAO");
      gl.bindVertexArray(vao);
      gl.enableVertexAttribArray(ATTR_SLOTS.a_corner);
      gl.vertexAttribPointer(ATTR_SLOTS.a_corner, 2, gl.FLOAT, false, 0, 0);
      gl.vertexAttribDivisor(ATTR_SLOTS.a_corner, 0);
      gl.bindVertexArray(null);
      if (gl.isContextLost()) throw new Error("xy: shared WebGL host context lost during setup");
      return { quad, vao };
    } catch (error) {
      if (!gl.isContextLost()) {
        if (vao) gl.deleteVertexArray(vao);
        if (quad) gl.deleteBuffer(quad);
      }
      throw error;
    }
  }

  private _createSharedQuad(): void {
    const { quad, vao } = this._buildSharedQuad(this.gl);
    this.sharedQuad = quad;
    this.sharedQuadVao = vao;
  }

  private _markLost(): void {
    if (this._disposed) return;
    if (!this.lost) {
      this.lost = true;
      this.ready = false;
      this.generation += 1;
      this._activeClient = null;
      this._dropSharedHandles();
      // Context-loss invalidates handles; clearing references is correct, but
      // issuing deleteShader against the lost namespace is not.
      this._dropShaderHandles();
      this._notify("_onGlHostContextLost");
    }
    this._scheduleRecovery();
  }

  private _clearRecoveryTimer(): void {
    if (this._recoveryTimer !== null) clearTimeout(this._recoveryTimer);
    this._recoveryTimer = null;
  }

  private _scheduleRecovery(): void {
    if (this._disposed || this._recoveryTimer !== null || (this.ready && !this.lost)) return;
    const delay = this._recoveryDelay;
    this._recoveryTimer = setTimeout(() => {
      this._recoveryTimer = null;
      this._replaceLostSurface();
    }, delay);
  }

  private _replaceLostSurface(): void {
    if (this._disposed || (this.ready && !this.lost)) return;
    let surface: GLHostSurface | null = null;
    let shared: SharedQuad | null = null;
    try {
      surface = this._createSurface();
      shared = this._buildSharedQuad(surface.gl);
    } catch (error) {
      if (surface && !surface.gl.isContextLost()) {
        if (shared?.vao) surface.gl.deleteVertexArray(shared.vao);
        if (shared?.quad) surface.gl.deleteBuffer(shared.quad);
        try { surface.gl.getExtension("WEBGL_lose_context")?.loseContext(); } catch (_cleanupError) {}
      }
      this._recoveryDelay = Math.min(
        RECOVERY_MAX_DELAY_MS,
        Math.max(RECOVERY_INITIAL_DELAY_MS, this._recoveryDelay * 2),
      );
      console.error("xy: shared WebGL host replacement failed", error);
      this._scheduleRecovery();
      return;
    }

    const oldCanvas = this.canvas;
    const oldGl = this.gl;
    this._detachSurfaceListeners(oldCanvas);
    this._dropShaderHandles();
    this.canvas = surface.canvas;
    this.gl = surface.gl;
    this._maxViewport = surface.maxViewport;
    this._maxVertexAttribs = surface.maxVertexAttribs;
    this._capacityWidth = 1;
    this._capacityHeight = 1;
    this.sharedQuad = shared.quad;
    this.sharedQuadVao = shared.vao;
    this._attachSurfaceListeners(this.canvas);
    this.lost = false;
    this.ready = true;
    this._recoveryDelay = RECOVERY_INITIAL_DELAY_MS;

    // If the old context managed to restore while the watchdog was allocating
    // its replacement, release it explicitly after detaching its callbacks.
    if (!oldGl.isContextLost()) {
      try { oldGl.getExtension("WEBGL_lose_context")?.loseContext(); } catch (_cleanupError) {}
    }
    this._notify("_onGlHostContextRestored");
    if (this.gl.isContextLost()) this._markLost();
  }

  private _dropSharedHandles(): void {
    this.sharedQuad = null;
    this.sharedQuadVao = null;
  }

  private _dropShaderHandles(): void {
    this._shaderCache.clear();
  }

  private _deleteCachedShaders(): void {
    for (const shaders of this._shaderCache.values()) {
      for (const shader of shaders.values()) this.gl.deleteShader(shader);
    }
    this._dropShaderHandles();
  }

  private _notify(method: keyof GLHostClient): void {
    // Snapshot the set: a lifecycle callback may destroy and release its view.
    for (const client of [...this._clients]) {
      if (this._disposed || !this._clients.has(client)) continue;
      const callback = client[method];
      if (typeof callback !== "function") continue;
      try {
        callback.call(client);
      } catch (error) {
        console.error(`xy: shared WebGL client ${String(method)} failed`, error);
      }
    }
  }

  private _dispose(): void {
    if (this._disposed || this._clients.size) return;
    this._disposed = true;
    this.ready = false;
    this._activeClient = null;
    this._clearRecoveryTimer();
    this._detachSurfaceListeners(this.canvas);
    if (!this.gl.isContextLost()) {
      this._deleteCachedShaders();
      if (this.sharedQuadVao) this.gl.deleteVertexArray(this.sharedQuadVao);
      if (this.sharedQuad) this.gl.deleteBuffer(this.sharedQuad);
      try { this.gl.getExtension("WEBGL_lose_context")?.loseContext(); } catch (_error) {}
    } else {
      this._dropShaderHandles();
    }
    this._dropSharedHandles();
    this._onDispose();
  }
}

/** Acquire and register with the document's singleton host.  `null` means the
 * feature gate selected the existing native-per-view context path. */
export function acquireGLHost(doc: Document, client: GLHostClient): GLHost | null {
  if (!doc || !client || !sharedHostEnabled(doc)) return null;
  let host = HOSTS.get(doc);
  // A chart created while the page host is recovering can use the governed
  // native path immediately; existing host clients will rejoin the restored
  // shared context through the host-wide lifecycle callback.
  if (host && (!host.ready || host.lost || host.gl.isContextLost())) return null;
  if (!host) {
    let created: GLHost;
    try {
      created = new GLHost(doc, () => {
        if (HOSTS.get(doc) === created) HOSTS.delete(doc);
      });
    } catch (_error) {
      // The visible per-chart canvas may still be able to acquire WebGL2 even
      // when allocating the detached shared host fails. Signal the caller to
      // take its governed native fallback instead of aborting construction.
      return null;
    }
    host = created;
    HOSTS.set(doc, host);
  }
  host._register(client);
  return host;
}
