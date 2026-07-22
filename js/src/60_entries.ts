import { bytesToSpan, decodeFrame, resolveColumnBuffers } from "./00_header";
import { ChartView } from "./50_chartview";
import { MARK_KINDS, markOf } from "./55_marks";
// Prototype-augmentation modules: imported for their side effect of attaching
// methods to ChartView.prototype. Every entry point must load them before the
// first ChartView is constructed.
import "./51_annotations";
import "./52_tooltip";
import "./53_interaction";
import "./54_kernel";
import "./56_animation";
import "./57_viewstate";

// ---------------------------------------------------------------------------
// Entry points
// ---------------------------------------------------------------------------

/** First-paint buffers in the shape the spec declares (§29): packed is one
 * blob; split is one span per column. Aligned views stay zero-copy; only a
 * legacy unaligned view pays a narrow view-sized copy. A spec/transport
 * disagreement is a bug, never a fallback. */
function payloadBuffers(spec, raw) {
  if (spec.buffer_layout === "split") {
    if (!Array.isArray(raw)) {
      throw new Error("xy: spec says buffer_layout=split but the transport delivered one buffer");
    }
    return raw.map(bytesToSpan);
  }
  if (Array.isArray(raw)) {
    throw new Error("xy: transport delivered a buffer list but the spec is not split-layout");
  }
  return bytesToSpan(raw);
}

export function render({ model, el }) {
  const spec = model.get("spec");
  const buffer = payloadBuffers(spec, model.get("buffers"));
  const comm = {
    send: (msg) => model.send(msg),
    wantsViewChange: () => spec.interaction?._transport_view_change === true,
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
export function renderStandalone(el, spec, arrayBuffer) {
  const buffer = bytesToSpan(arrayBuffer);
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

// Public API. The ESM bundle (static/index.js, anywidget's `_esm`) re-exports
// these directly; the IIFE bundle (static/standalone.js) exposes the same
// namespace as `window.xy`.
export { decodeFrame, resolveColumnBuffers, ChartView, MARK_KINDS, markOf };
export default { render, decodeFrame };
