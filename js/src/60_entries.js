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

/** First-paint buffers in the shape the spec declares (§29): packed is one
 * blob; split is one ArrayBuffer per column — slicing each incoming frame
 * separately also guarantees Float32Array alignment. A spec/transport
 * disagreement is a bug, never a fallback. */
function payloadBuffers(spec, raw) {
  if (spec.buffer_layout === "split") {
    if (!Array.isArray(raw)) {
      throw new Error("xy: spec says buffer_layout=split but the transport delivered one buffer");
    }
    return raw.map(bytesToArrayBuffer);
  }
  if (Array.isArray(raw)) {
    throw new Error("xy: transport delivered a buffer list but the spec is not split-layout");
  }
  return bytesToArrayBuffer(raw);
}

function render({ model, el }) {
  const spec = model.get("spec");
  const buffer = payloadBuffers(spec, model.get("buffers"));
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

/** Standalone (static HTML export — no kernel). Retains typed CPU views of
 * shipped channels so hover can read approximate values without a kernel (§37). */
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

// Everything from the next line on is stripped for the IIFE/standalone build
// (ES `export` is illegal in a `new Function` body). The marker must be the
// whole line — build.mjs splits on it and rejects any trailing text so this
// description can never leak into the ESM bundle as bare code.
// ---- exports ----
export { render, renderStandalone, ChartView, MARK_KINDS, markOf };
export default { render };
