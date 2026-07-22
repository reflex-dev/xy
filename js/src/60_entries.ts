import { bytesToSpan, decodeFrame, payloadBuffers, payloadCoherent } from "./00_header";
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

export function render({ model, el }) {
  const spec = model.get("spec");
  const buffer = payloadBuffers(spec, model.get("buffers"));
  const comm = {
    send: (msg) => model.send(msg),
    // Read the live spec: appends re-sync it, and the transport flag must
    // survive them (it is re-applied kernel-side on every append).
    wantsViewChange: () => model.get("spec")?.interaction?._transport_view_change === true,
    onMessage: (cb) => {
      const handler = (content, buffers) => cb(content, buffers);
      model.on("msg:custom", handler);
      return () => model.off?.("msg:custom", handler);
    },
  };
  const view = new ChartView(el, spec, buffer, comm);
  // Streaming append rides the spec+buffers trait update itself (§29): one
  // comm message per tick that doubles as notebook-reopen state. A fresh
  // render above already painted the streamed state, so only a *subsequent*
  // advance of `spec.append.seq` applies as an incremental append.
  //
  // Hosts are not guaranteed to set the two traits atomically: one change
  // event may fire between the spec write and the buffers write (in either
  // order). Both events funnel here, a torn pair (a column that no longer
  // fits its buffer) defers without consuming the seq, and applied state is
  // keyed on (seq, buffers identity) — so if a same-length torn pair slips
  // past the fit check, the buffers' own change event re-applies and repairs.
  const applied = { seq: spec.append?.seq ?? null, buffers: model.get("buffers") };
  const onAppendState = () => {
    const nextSpec = model.get("spec");
    const tag = nextSpec?.append;
    if (!tag) return;
    const nextBuffers = model.get("buffers");
    if (tag.seq === applied.seq && nextBuffers === applied.buffers) return;
    if (!payloadCoherent(nextSpec, nextBuffers)) return; // torn: wait for the pair
    applied.seq = tag.seq;
    applied.buffers = nextBuffers;
    view._applyAppend({ type: "append", affected: tag.affected, spec: nextSpec }, nextBuffers);
  };
  model.on("change:spec", onAppendState);
  model.on("change:buffers", onAppendState);
  return () => {
    model.off?.("change:spec", onAppendState);
    model.off?.("change:buffers", onAppendState);
    view.destroy();
  };
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
export { decodeFrame, ChartView, MARK_KINDS, markOf };
export default { render, decodeFrame };
