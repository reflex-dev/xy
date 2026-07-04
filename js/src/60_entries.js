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
    onMessage: (cb) => {
      const handler = (content, buffers) => cb(content, buffers);
      model.on("msg:custom", handler);
      return () => model.off?.("msg:custom", handler);
    },
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
